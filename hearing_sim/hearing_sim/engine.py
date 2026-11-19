"""STFT 重叠相加处理引擎 —— 系统核心。

两条通路
--------
unaided (助听前):  分带 Power Law 重振 -> 听阈门限 -> 频谱展宽
aided   (助听后):  8 通道 WDRC (轻声/大声分压缩) -> 泄漏自动补偿的目标增益
                   -> 啸叫检测与陷波抑制

设计目标: 32 kHz 单声道, n_fft=1024 / hop=256 (12.5 ms 帧移),
60 秒音频处理 <= 2 秒 (见 tests/test_performance.py)。
所有逐帧运算均为 numpy 向量化, 无 Python 帧循环内的标量运算。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .compressor import WDRC, build_static_curve
from .feedback import FeedbackDetector, SpectralNotchSuppressor
from .filterbank import CENTER_FREQS, N_CHANNELS, spectral_band_masks
from .leakage import FITTING_CLOSED, FITTING_OPEN, compensate_gains
from .loss_sim import CAL_DB_SPL, build_loss_parameters, loudness_map_db
from .prescription import DEFAULT_LDL_HL, prescription_targets

N_FFT = 1024
HOP = 256


def hann_window(n: int) -> np.ndarray:
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)


def stft_scale_factor(win: np.ndarray) -> float:
    """STFT 分带幅度 -> 时域 RMS 的 Parseval 缩放因子 (已用已知 RMS 纯音标定)。

    对实信号 rfft 只保留正频率, Parseval 比值为 0.5, 故:
        rms_band = sqrt(2 * sum_band |X[k]|^2 / (N * sum_n w[n]^2))
                 = sqrt(2) * sqrt(sum_band |X|^2) / (N * sqrt(mean(w^2)))
    纯音标定: N=1024 Hann, 全频带还原误差 <1%。
    """
    n = len(win)
    return np.sqrt(2.0) / (n * float(np.sqrt(np.mean(win**2))))


def stft(x: np.ndarray, n_fft: int = N_FFT, hop: int = HOP) -> tuple[np.ndarray, np.ndarray]:
    """返回 (frames, bins) 复数谱与窗函数。末尾补零。"""
    win = hann_window(n_fft)
    n_frames = 1 + max(0, (len(x) - n_fft) // hop)
    pad = max(0, n_frames * hop + n_fft - len(x))
    xp = np.pad(x, (0, pad))
    idx = np.arange(n_frames)[:, None] * hop + np.arange(n_fft)[None, :]
    frames = xp[idx] * win[None, :]
    return np.fft.rfft(frames, axis=1), win


def istft(spec: np.ndarray, win: np.ndarray, hop: int = HOP, length: int | None = None) -> np.ndarray:
    """重叠相加重构, Hann 窗 COLA 归一化。"""
    n_fft = len(win)
    frames = np.fft.irfft(spec, n=n_fft, axis=1) * win[None, :]
    n_frames = frames.shape[0]
    out = np.zeros(n_frames * hop + n_fft)
    norm = np.zeros_like(out)
    for i in range(n_frames):
        s = i * hop
        out[s:s + n_fft] += frames[i]
        norm[s:s + n_fft] += win**2
    out /= np.maximum(norm, 1e-12)
    if length is not None:
        out = out[:length]
    return out


@dataclass
class EngineConfig:
    fitting: str = FITTING_OPEN           # open / closed
    formula: str = "WDRC"                 # NAL-R / NAL-RP / WDRC
    feedback_margin_db: float = 6.0       # 泄漏补偿受反馈余量限制
    enable_smearing: bool = True
    enable_gate: bool = True
    enable_feedback: bool = True
    feedback_threshold_db: float = 12.0
    feedback_persistence: int = 16
    notch_q: float = 25.0
    notch_depth_db: float = 15.0
    calibration_db_spl: float = CAL_DB_SPL
    ldl_hl: float = DEFAULT_LDL_HL
    attack_ms: float = 5.0
    release_ms: float = 80.0


@dataclass
class EngineResult:
    unaided: np.ndarray
    aided: np.ndarray
    fs: int
    targets: dict
    leakage: dict
    detected_howls: list = field(default_factory=list)
    notch_history: list = field(default_factory=list)


class FittingEngine:
    """助听模拟引擎, 一个实例对应一张听力图 + 一套配置。"""

    def __init__(self, audiogram, fs: int, config: EngineConfig | None = None):
        self.audiogram = audiogram
        self.fs = fs
        self.cfg = config or EngineConfig()

        # 处方目标 + 泄漏补偿
        targets = prescription_targets(audiogram, self.cfg.formula)
        leak = compensate_gains(
            targets["gains65"], CENTER_FREQS, self.cfg.fitting, self.cfg.feedback_margin_db
        )
        if targets["gain_table"] is not None:
            table = targets["gain_table"].copy()
            # 泄漏补偿作用于整张非线性表 (低频各输入级一致补偿)
            table += leak["compensation_db"][:, None]
            input_levels = targets["input_levels"]
        else:
            table = None
            input_levels = None
        input_levels, gain_table = build_static_curve(
            table, input_levels, leak["compensated_gains"], targets["compression_ratios"]
        )
        self.targets = targets
        self.leakage = leak
        self.compressor = WDRC(
            input_levels, gain_table, targets["ldl_spl"], fs, HOP,
            attack_ms=self.cfg.attack_ms, release_ms=self.cfg.release_ms,
            calibration_db_spl=self.cfg.calibration_db_spl,
        )

        self.masks = spectral_band_masks(N_FFT, fs)
        # 每个 bin 所属通道编号, 用于向量化的分带聚合
        self.band_of_bin = np.zeros(len(self.masks[0]), dtype=np.int32)
        for k, m in enumerate(self.masks):
            self.band_of_bin[m] = k
        self.bin_freqs = np.fft.rfftfreq(N_FFT, 1.0 / fs)
        self.loss_params = build_loss_parameters(audiogram, self.bin_freqs, self.cfg.ldl_hl)
        # STFT 幅度 -> 时域 RMS 的 Parseval 缩放
        self._rms_scale = stft_scale_factor(hann_window(N_FFT))
        self._ldl = self.targets["ldl_spl"]

        self.detector = FeedbackDetector(
            fs, N_FFT, threshold_db=self.cfg.feedback_threshold_db,
            persistence_frames=self.cfg.feedback_persistence,
        )
        self.suppressor = SpectralNotchSuppressor(
            fs, N_FFT, q=self.cfg.notch_q, depth_db=self.cfg.notch_depth_db,
        )

    # ------------------------------------------------------------------
    def _normalize_input(self, x: np.ndarray, working_rms: float = 0.05) -> tuple[np.ndarray, float]:
        """输入级归一化: 把 RMS 拉到工作点 (默认 -26 dBFS), 模拟助听器输入 AGC。

        返回 (归一化信号, 应用的 dB 增益)。保持相对动态与频带形状,
        仅整体平移到器件线性工作区, 给处方增益预留 headroom。
        """
        rms = float(np.sqrt(np.mean(x**2))) if x.size else 0.0
        if rms <= 1e-9:
            return x, 0.0
        g = working_rms / rms
        return (x * g).astype(np.float32), float(20.0 * np.log10(g))

    def _band_rms(self, mag: np.ndarray) -> np.ndarray:
        """向量化: 一次 bincount 算出 8 个通道各自的时域等效 RMS。"""
        sum_sq = np.bincount(self.band_of_bin, weights=mag**2, minlength=N_CHANNELS)
        return self._rms_scale * np.sqrt(np.maximum(sum_sq, 1e-20))

    def _apply_ospl90(self, frame: np.ndarray) -> np.ndarray:
        """频域 OSPL90: 逐带把输出 RMS 声级限制在 LDL 天花板内 (向量化)。

        LDL 是带 RMS 量级 (非单 bin 峰值谱级), 用 Parseval 缩放还原再比对。
        """
        mag = np.abs(frame)
        band_spl = 20.0 * np.log10(np.maximum(self._band_rms(mag), 1e-10)) \
            + self.cfg.calibration_db_spl
        over = band_spl - self._ldl
        if not np.any(over > 0):
            return frame
        att_per_band = np.where(over > 0, 10.0 ** (-np.maximum(over, 0) / 20.0), 1.0)
        att_per_bin = att_per_band[self.band_of_bin]
        return frame * att_per_bin

    # ------------------------------------------------------------------
    def process_unaided(self, x: np.ndarray) -> np.ndarray:
        """助听前: 听损模拟通路 (阈下门限 + 重振响度映射 + 频谱展宽)。"""
        x, _ = self._normalize_input(x)
        spec, win = stft(x, N_FFT, HOP)
        mag = np.abs(spec)
        phase = np.angle(spec)

        # 1) 每 bin 输入级 dB SPL
        input_db = 20.0 * np.log10(np.maximum(mag, 1e-8)) + self.cfg.calibration_db_spl

        # 2) dB 域响度映射 (阈下门限 / 中间重振压缩 / LDL 钳制)
        out_db = loudness_map_db(
            input_db,
            self.loss_params["threshold_spl"][None, :],
            self.loss_params["ldl_spl"][None, :],
        )
        # 输出级转回线性幅度 (保持原相位)
        mag = 10.0 ** ((out_db - self.cfg.calibration_db_spl) / 20.0)

        # 3) 频谱展宽 (清晰度下降), 矩阵逐行归一化保持能量
        if self.cfg.enable_smearing:
            mag = mag @ self.loss_params["smear_matrix"].T

        out_spec = mag * np.exp(1j * phase)
        y = istft(out_spec, win, HOP, len(x))
        peak = np.max(np.abs(y)) if y.size else 0.0
        if peak > 0.99:
            y = y * (0.99 / peak)
        return y

    # ------------------------------------------------------------------
    def process_aided(self, x: np.ndarray) -> tuple[np.ndarray, list, list]:
        """助听后: WDRC + 反馈抑制通路。返回 (音频, 啸叫记录, 陷波历史)。"""
        x, _ = self._normalize_input(x)
        spec, win = stft(x, N_FFT, HOP)
        n_frames = spec.shape[0]
        out = np.zeros_like(spec)
        self.compressor.reset()
        howl_log: list[tuple[int, float, float]] = []
        notch_log: list[list[float]] = []

        for t in range(n_frames):
            frame = spec[t]
            mag = np.abs(frame)

            # 啸叫检测在压缩前的输入谱上做: 保留语音自然起伏, 避免 WDRC
            # 把间歇语音抹平成稳态信号而误报 (真实助听器反馈检测也在前级)
            howls = []
            if self.cfg.enable_feedback:
                in_mag_db = 20.0 * np.log10(np.maximum(mag, 1e-8)) \
                    + self.cfg.calibration_db_spl
                howls = self.detector.update(in_mag_db)
                for f0, strength in howls:
                    howl_log.append((t, f0, strength))
                self.suppressor.update_notches(howls)

            # 向量化分带 RMS -> WDRC 线性增益 -> 按 bin 广播
            rms = self._band_rms(mag)
            gains = self.compressor.process_frame(rms)
            frame = frame * gains[self.band_of_bin]

            # OSPL90 逐带天花板 (LDL 限幅)
            frame = self._apply_ospl90(frame)

            # 陷波抑制作用于压缩后输出
            if self.cfg.enable_feedback and self.suppressor.active:
                frame = self.suppressor.apply(frame)
                notch_log.append(list(self.suppressor.active.keys()))
            elif self.cfg.enable_feedback:
                notch_log.append([])
            out[t] = frame

        y = istft(out, win, HOP, len(x))
        # OSPL90 天花板: 仅极端超限才整体回落, 正常工作区不受影响
        peak = np.max(np.abs(y))
        if peak > 0.99:
            y = y * (0.99 / peak)
        return y, howl_log, notch_log

    # ------------------------------------------------------------------
    def process(self, x: np.ndarray) -> EngineResult:
        unaided = self.process_unaided(x)
        aided, howl_log, notch_log = self.process_aided(x)
        return EngineResult(
            unaided=unaided, aided=aided, fs=self.fs,
            targets=self.targets, leakage=self.leakage,
            detected_howls=howl_log, notch_history=notch_log,
        )
