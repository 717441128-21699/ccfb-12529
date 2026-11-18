"""助听器整机处理引擎（八通道 STFT 矢量化通路）。

处理链
======
麦克风信号 -> STFT -> 八通道电平估计
        -> 处方目标(NAL-R/NAL-RP/POGO) + 耳模漏音自动补偿
        -> 分通道 WDRC（轻声线性/中间压缩/大声限幅）
        -> 啸叫频点检测 + 自适应陷波
        -> ISTFT -> 受话器输出

另提供裸耳听损模拟入口（loss_sim.simulate_unaided）与
带 NLMS 自适应反馈抵消的闭环通路。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal

from .audiogram import Audiogram
from .config import (BAND_EDGES, CHANNEL_FREQS, DEFAULT_CAL_DB_SPL,
                     DEFAULT_SR, HOP, N_FFT)
from .coupling import compensated_targets
from .feedback import (AdaptiveFeedbackCanceller, HowlDetector,
                       apply_notches_stft)
from .loss_sim import simulate_unaided
from .prescription import target_gain
from .spectral import band_levels_db_spl, band_membership, istft, stft
from .wdrc import wdrc_gain_curve


@dataclass
class FittingReport:
    """一次验配的完整参数，供界面展示与指标核对。"""
    channel_freqs: np.ndarray
    prescription_db: np.ndarray          # 处方原始目标
    vent_loss_db: np.ndarray             # 耳模漏音量
    vent_comp_db: np.ndarray             # 实际补偿量（经稳定/上限约束）
    target_db: np.ndarray                # 最终通道目标
    measured_65_db: np.ndarray | None = None   # 65 dB SPL 实测增益
    howls: list = field(default_factory=list)
    formula: str = "nal-r"
    coupling: str = "open"


class HearingAidEngine:
    def __init__(self, audiogram: Audiogram, sr: int = DEFAULT_SR,
                 formula: str = "nal-r", coupling: str = "open",
                 cal_db_spl: float = DEFAULT_CAL_DB_SPL,
                 enable_feedback: bool = True,
                 n_fft: int = N_FFT, hop: int = HOP):
        if coupling not in ("open", "closed"):
            raise ValueError("coupling 只支持 'open' / 'closed'")
        self.audiogram = audiogram
        self.sr = sr
        self.formula = formula
        self.coupling = coupling
        self.cal_db_spl = cal_db_spl
        self.enable_feedback = enable_feedback
        self.n_fft = n_fft
        self.hop = hop

        self.hl_channels = audiogram.hl_at(CHANNEL_FREQS)
        self._membership: np.ndarray | None = None
        self._bin_freqs: np.ndarray | None = None
        self.howls: list = []
        self.report: FittingReport | None = None
        self._build_targets(howl_freqs=())

    # ------------------------------------------------------------ 目标计算
    def _build_targets(self, howl_freqs=()) -> FittingReport:
        from .coupling import insertion_loss, vent_compensation
        raw = target_gain(self.audiogram, CHANNEL_FREQS, self.formula)
        il = insertion_loss(CHANNEL_FREQS, self.coupling)
        comp = vent_compensation(CHANNEL_FREQS, self.coupling, howl_freqs)
        final = raw + comp
        self.report = FittingReport(
            channel_freqs=CHANNEL_FREQS.copy(),
            prescription_db=raw,
            vent_loss_db=il,
            vent_comp_db=comp,
            target_db=final,
            howls=list(self.howls),
            formula=self.formula,
            coupling=self.coupling,
        )
        return self.report

    # ------------------------------------------------------------ 主通路
    def process_aided(self, x: np.ndarray,
                      detect_howls: bool | None = None) -> np.ndarray:
        """戴机模拟：返回助听器处理后的时域信号。"""
        x = np.asarray(x, dtype=float)
        if detect_howls is None:
            detect_howls = self.enable_feedback

        spec, bin_freqs, _ = stft(x, self.sr, self.n_fft, self.hop)
        self._bin_freqs = bin_freqs
        self._membership = band_membership(bin_freqs, BAND_EDGES)

        # 1) 啸叫检测（在干信号上找持续纯音频点），并据此重建补偿目标
        if detect_howls:
            power_db = 20 * np.log10(np.maximum(np.abs(spec), 1e-10))
            detector = HowlDetector(bin_freqs, self.sr / self.hop)
            self.howls = detector.detect(power_db)
            if self.howls:
                self._build_targets([h.freq_hz for h in self.howls])
                self.report.howls = list(self.howls)
            spec = apply_notches_stft(spec, bin_freqs, self.howls)

        # 2) 通道电平
        levels = band_levels_db_spl(spec, self._membership, self.cal_db_spl)

        # 3) 每通道 WDRC 增益曲线
        n_frames = spec.shape[0]
        gains_db = np.zeros((n_frames, len(CHANNEL_FREQS)))
        for ch in range(len(CHANNEL_FREQS)):
            gains_db[:, ch] = wdrc_gain_curve(
                levels[:, ch], self.report.target_db[ch],
                self.hl_channels[ch], self.sr, self.hop,
            )

        # 4) 映射回 bin 并施加（通道增益经 membership 映射到 STFT bin）
        bin_gain = 10 ** (gains_db / 20.0) @ self._membership
        spec = spec * bin_gain

        y = istft(spec, self.sr, self.n_fft, self.hop, length=len(x))
        # 5) MPO 最大输出限制：软限幅在 0.95 FS 起作用，保留波形包络、
        #    避免硬削顶的谐波失真（真实助听器的输出限幅同理）
        peak = np.max(np.abs(y))
        mpo_threshold = 0.95
        if peak > mpo_threshold:
            y = mpo_threshold * np.tanh(y / mpo_threshold)
        return y

    # -------------------------------------------------- 带自适应反馈抵消
    def process_with_afc(self, source: np.ndarray, feedback_ir: np.ndarray,
                         n_taps: int = 64, mu: float = 0.05
                         ) -> tuple[np.ndarray, AdaptiveFeedbackCanceller]:
        """闭环通路：受话器信号经反馈路径回到麦克风，AFC 在线抵消。

        为保证速度，AFC 按 256 样点块运行，反馈卷积用带状态的 lfilter；
        抵消后的完整麦克风流再走标准矢量化戴机链。
        """
        source = np.asarray(source, dtype=float)
        afc = AdaptiveFeedbackCanceller(n_taps=n_taps, mu=mu)
        block = self.hop
        n = len(source)
        err = np.zeros(n)
        y_prev = np.zeros(block)
        zi = np.zeros(max(len(feedback_ir) - 1, 0))
        for start in range(0, n, block):
            end = min(start + block, n)
            fb, zi = signal.lfilter(feedback_ir, 1.0, y_prev, zi=zi)
            mic = source[start:end] + fb[:end - start]
            e = afc.process_block(mic, y_prev[:end - start])
            err[start:end] = e
            y_prev = np.pad(e, (0, block - len(e)))[:block]
        y = self.process_aided(err, detect_howls=False)
        return y, afc

    # ------------------------------------------------------------ 裸耳
    def process_unaided(self, x: np.ndarray,
                        rng: np.random.Generator | None = None) -> np.ndarray:
        return simulate_unaided(x, self.sr, self.audiogram, rng=rng)

    # ------------------------------------------------------------ 验证
    def measure_band_gain(self, dry: np.ndarray, proc: np.ndarray) -> np.ndarray:
        """测量处理前后八通道电平差（dB），用于核对处方符合度。

        采用与临床真耳分析仪一致的时域带通滤波测量：对每个通道用
        Butterworth 带通分离后比较 RMS，避免 STFT 在最低频带（仅 2-3 个
        bin）的窗泄漏导致的系统性偏差。
        """
        from scipy import signal as _sig
        gains = np.zeros(len(CHANNEL_FREQS))
        for ch in range(len(CHANNEL_FREQS)):
            lo = max(BAND_EDGES[ch] / (self.sr / 2), 1e-4)
            hi = min(BAND_EDGES[ch + 1] / (self.sr / 2), 0.999)
            sos = _sig.butter(4, [lo, hi], btype="band", output="sos")
            p_dry = np.mean(_sig.sosfilt(sos, dry) ** 2) + 1e-20
            p_proc = np.mean(_sig.sosfilt(sos, proc) ** 2) + 1e-20
            gains[ch] = 10 * np.log10(p_proc / p_dry)
        return gains


# ---------------------------------------------------------------- 便捷函数
def process_aided(x: np.ndarray, audiogram: Audiogram, sr: int = DEFAULT_SR,
                  formula: str = "nal-r", coupling: str = "open",
                  **kw) -> tuple[np.ndarray, HearingAidEngine]:
    eng = HearingAidEngine(audiogram, sr=sr, formula=formula,
                           coupling=coupling, **kw)
    return eng.process_aided(x), eng


def process_unaided(x: np.ndarray, audiogram: Audiogram,
                    sr: int = DEFAULT_SR, **kw) -> np.ndarray:
    eng = HearingAidEngine(audiogram, sr=sr, **kw)
    return eng.process_unaided(x)
