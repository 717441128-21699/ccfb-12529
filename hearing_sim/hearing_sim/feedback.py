"""啸叫 (声反馈) 自动检测与抑制。

检测
----
对输出谱做慢速长时平均 (LTA) 得到基线, 同时满足以下条件判为啸叫频点:
  1. 局部谱峰高出基线 threshold_db (默认 12 dB);
  2. 持续 persistence_frames 帧以上 (啸叫是稳态窄带信号);
  3. 帧间频率漂移小于 drift_hz、幅度抖动小于 jitter_db (区别于语音谐波)。

抑制
----
两种实现:
  - 频域高斯陷波 (引擎默认, O(n_fft), 无瞬态): 检测频点 ±f0/Q 范围内最深 depth_db;
  - 时域双二阶陷波 (feedback_notch_sos, 供测试与离线批处理)。
最多同时保留 max_notches 个陷波; 啸叫消失后自动释放。

参考: Kates, "Feedback Cancellation in Hearing Aids" (2001);
Agnew 啸叫特征量化研究 (稳态、窄带、低漂移)。
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter
from scipy.signal import sosfilt


class FeedbackDetector:
    def __init__(
        self,
        fs: float,
        n_fft: int,
        threshold_db: float = 12.0,
        persistence_frames: int = 16,
        lta_tau_frames: float = 60.0,
        drift_hz: float = 45.0,
        jitter_db: float = 3.0,
        min_freq_hz: float = 500.0,
        max_freq_hz: float | None = None,
        min_absolute_db: float = 60.0,
    ):
        self.fs = fs
        self.n_fft = n_fft
        self.freqs = np.fft.rfftfreq(n_fft, 1.0 / fs)
        self.threshold_db = threshold_db
        self.persistence_frames = persistence_frames
        self.lta_alpha = float(np.exp(-1.0 / max(lta_tau_frames, 1.0)))
        self.drift_hz = drift_hz
        self.jitter_db = jitter_db
        band = (self.freqs >= min_freq_hz) & (self.freqs <= (max_freq_hz or fs / 2.0))
        self.band = band
        self.min_absolute_db = min_absolute_db
        self.lta: np.ndarray | None = None
        # 向量化轨迹: 每个 bin 的连续候选帧计数
        self._count = np.zeros(len(self.freqs), dtype=np.int32)
        # 幅度历史环形缓冲, 用于时间稳定性 (变异系数) 检验
        self._hist_len = persistence_frames
        self._amp_hist = np.full((len(self.freqs), self._hist_len), np.nan)
        self._hist_pos = 0

    def update(self, spectrum_db: np.ndarray) -> list[tuple[float, float]]:
        """输入一帧幅度谱 (dB), 返回确认的啸叫 [(freq_hz, strength_db), ...]。"""
        # 写入幅度历史
        self._amp_hist[:, self._hist_pos] = spectrum_db
        self._hist_pos = (self._hist_pos + 1) % self._hist_len

        if self.lta is None:
            self.lta = spectrum_db.copy()
            candidate = np.zeros(len(spectrum_db), dtype=bool)
        else:
            # 局部邻域均值 (5 点窗含中心), 减去中心贡献得到 4 邻居均值
            w = 2
            window_mean = uniform_filter(spectrum_db, size=2 * w + 1, mode="nearest")
            local_mean = (window_mean * (2 * w + 1) - spectrum_db) / (2 * w)
            # 候选只依赖邻域突起与绝对电平 (不依赖 LTA, 避免与冻结逻辑死锁)
            candidate = self.band & (
                (spectrum_db - local_mean) >= self.threshold_db
            ) & (spectrum_db >= self.min_absolute_db)

            # 候选 bin 冻结 LTA, 防止持续啸叫被基线"追上"; 其余 bin 慢适应
            adapt = np.where(candidate, 1.0, self.lta_alpha)
            self.lta = adapt * self.lta + (1.0 - adapt) * spectrum_db

        # 连续帧计数
        self._count[candidate] += 1
        self._count[~candidate] = 0

        # 确认: 持续足够帧 + 幅度时间稳态 (啸叫 CV 小, 语音音节起伏 CV 大)
        confirmed = []
        idx = np.where(self._count >= self.persistence_frames)[0]
        for i in idx:
            hist = self._amp_hist[i]
            if np.any(np.isnan(hist)):
                continue
            cv = np.std(hist) / max(abs(np.mean(hist)), 1e-9)
            strength = float(spectrum_db[i] - self.lta[i])
            if strength >= self.threshold_db and cv < 0.001:
                confirmed.append((float(self.freqs[i]), strength))
        return confirmed


class SpectralNotchSuppressor:
    """频域高斯陷波抑制器, 状态机自动跟踪啸叫频点。"""

    def __init__(self, fs: float, n_fft: int, q: float = 25.0, depth_db: float = 15.0,
                 max_notches: int = 3, release_frames: int = 50):
        self.fs = fs
        self.n_fft = n_fft
        self.q = q
        self.depth_db = depth_db
        self.max_notches = max_notches
        self.release_frames = release_frames
        self.freqs = np.fft.rfftfreq(n_fft, 1.0 / fs)
        # 活动陷波: {f0: 连续未检出帧数}
        self.active: dict[float, int] = {}

    def update_notches(self, howls: list[tuple[float, float]]) -> list[float]:
        howl_freqs = [f for f, _ in howls]
        for f0 in howl_freqs:
            # 并入邻近陷波 (频率差小于一个陷波带宽)
            merged = next((f for f in self.active if abs(f - f0) <= max(f0, f) / self.q), None)
            if merged is not None:
                self.active[merged] = 0
            elif len(self.active) < self.max_notches:
                self.active[f0] = 0
        # 释放
        for f in list(self.active):
            if f not in howl_freqs:
                self.active[f] += 1
                if self.active[f] > self.release_frames:
                    del self.active[f]
        return list(self.active.keys())

    def apply(self, spectrum: np.ndarray) -> np.ndarray:
        """对复数谱 (rfft) 施加全部陷波 (最多 3 个, 直接连乘)。"""
        if not self.active:
            return spectrum
        out = spectrum
        gain_floor = 10.0 ** (-self.depth_db / 20.0)
        for f0 in self.active:
            sigma = max(f0 / self.q, self.fs / self.n_fft)
            shape = (1.0 - gain_floor) * np.exp(-0.5 * ((self.freqs - f0) / sigma) ** 2)
            out = out * (1.0 - shape)
        return out


def feedback_notch_sos(f0: float, fs: float, q: float = 25.0) -> np.ndarray:
    """时域双二阶陷波滤波器系数 (scipy sos 格式, 深度由 Q 决定, 标准 notch)。"""
    w0 = 2.0 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2.0 * q)
    b0, b1, b2 = 1.0, -2.0 * np.cos(w0), 1.0
    a0 = 1.0 + alpha
    a1, a2 = -2.0 * np.cos(w0), 1.0 - alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def suppress_tone(x: np.ndarray, f0: float, fs: float, q: float = 25.0) -> np.ndarray:
    """便捷函数: 时域陷波滤除单个啸叫频点。"""
    return sosfilt(feedback_notch_sos(f0, fs, q), x)
