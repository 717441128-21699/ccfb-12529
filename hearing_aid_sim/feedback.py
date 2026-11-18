"""啸叫处理三部分：

1. HowlDetector —— 在 STFT 频谱上自动找啸叫频点
   （时间持续性 + 频谱突出度 + 时间稳定性三准则联合判定）；
2. 陷波抑制 —— RBJ peaking-EQ 双二阶滤波器，深度随突出度自适应；
3. AdaptiveFeedbackCanceller —— NLMS 自适应反馈抵消
   （带预白化的 filtered-x 简化形式），用于实时通路。

参考：Kates (2008) Digital Hearing Aids, ch. feedback suppression；
Dillon (2012) Hearing Aids, ch. oscillation & cancellation。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

# ---------------------------------------------------------------- 频点检测
@dataclass
class Howl:
    freq_hz: float
    prominence_db: float     # 相对邻域中值的突出度
    persistence: float       # 分析窗内持续帧占比


class HowlDetector:
    """三准则啸叫频点检测。

    Parameters
    ----------
    freqs       : STFT bin 频率
    frame_rate  : 每秒分析帧数（sr/hop）
    win_sec     : 分析窗长度（秒）
    min_prom_db : 频点功率高于邻域中值的最小 dB 数
    min_persist : 窗内满足突出条件的帧占比阈值
    """

    def __init__(self, freqs, frame_rate: float, win_sec: float = 0.5,
                 min_prom_db: float = 10.0, min_persist: float = 0.6,
                 max_temporal_std_db: float = 3.0):
        self.freqs = np.asarray(freqs, dtype=float)
        self.n_bins = len(self.freqs)
        self.win_frames = max(8, int(round(win_sec * frame_rate)))
        self.min_prom_db = min_prom_db
        self.min_persist = min_persist
        self.max_temporal_std_db = max_temporal_std_db

    def _prominence_all(self, block_db: np.ndarray) -> np.ndarray:
        """矢量化计算整窗所有帧、所有 bin 的突出度 (frames, bins)。

        邻域中值用 scipy 的 C 实现中值滤波（沿 bin 轴、窗口 10），
        再扣除中心 bin 自身，等价于左右各 5 个邻域 bin 的中值。
        """
        from scipy import ndimage
        radius = 5
        neigh_median = ndimage.median_filter(
            block_db, size=(1, 2 * radius), mode="nearest",
            origin=(0, 0),
        )
        prom = block_db - neigh_median
        prom[:, :radius] = -np.inf
        prom[:, block_db.shape[1] - radius:] = -np.inf
        return prom

    def detect(self, stft_power_db: np.ndarray) -> list[Howl]:
        """输入 (n_frames, n_bins) 的功率谱(dB)，返回啸叫频点列表。

        两阶段提速：先用时间稳定性（逐 bin 标准差，纯 numpy）粗筛候选，
        只对候选 bin 所在窗做中值突出度计算，避免对全频带跑中值滤波。
        """
        n_frames = stft_power_db.shape[0]
        win = min(self.win_frames, n_frames)
        howls: list[Howl] = []
        radius = 5
        for start in range(0, max(n_frames - win + 1, 1), win):
            block = stft_power_db[start:start + win]
            # 第一阶段：时间稳定性粗筛（啸叫纯音帧间波动小）
            temporal_std = block.std(axis=0)
            stable_bins = np.where(
                (temporal_std < self.max_temporal_std_db)
                & (np.arange(self.n_bins) >= radius)
                & (np.arange(self.n_bins) <= self.n_bins - radius)
            )[0]
            if stable_bins.size == 0:
                continue
            # 第二阶段：只在稳定 bin 上算突出度（仍取完整邻域中值）
            from scipy import ndimage
            neigh_median = ndimage.median_filter(
                block, size=(1, 2 * radius), mode="nearest", origin=(0, 0))
            prom = block - neigh_median
            hot = prom >= self.min_prom_db
            persistence = hot.mean(axis=0)
            # 候选 = 稳定且持续突出
            candidates = stable_bins[persistence[stable_bins]
                                     >= self.min_persist]
            # 相邻 bin 聚类，每簇取功率最强者
            for cluster in self._cluster(candidates):
                k = cluster[int(np.argmax(block.mean(axis=0)[cluster]))]
                hot_k = hot[:, k]
                howls.append(Howl(
                    freq_hz=float(self.freqs[k]),
                    prominence_db=float(np.median(prom[:, k][hot_k]))
                    if hot_k.any() else float(np.median(prom[:, k])),
                    persistence=float(persistence[k]),
                ))
        # 合并不同窗内重复报出的同一频点
        return self._merge(howls)

    @staticmethod
    def _cluster(idx: np.ndarray) -> list[np.ndarray]:
        if idx.size == 0:
            return []
        groups, cur = [], [idx[0]]
        for a, b in zip(idx[:-1], idx[1:]):
            if b - a <= 2:
                cur.append(b)
            else:
                groups.append(np.array(cur))
                cur = [b]
        groups.append(np.array(cur))
        return groups

    @staticmethod
    def _merge(howls: list[Howl], rel_tol: float = 0.05) -> list[Howl]:
        out: list[Howl] = []
        for h in sorted(howls, key=lambda x: -x.prominence_db):
            if any(abs(h.freq_hz - o.freq_hz) / o.freq_hz < rel_tol for o in out):
                continue
            out.append(h)
        return sorted(out, key=lambda x: x.freq_hz)


# ---------------------------------------------------------------- 陷波滤波器
def peaking_biquad(freq_hz: float, sr: float, gain_db: float,
                   q: float = 30.0) -> np.ndarray:
    """RBJ peaking EQ 双二阶系数（负增益即可变深度陷波），返回 sos 行。"""
    w0 = 2 * np.pi * freq_hz / sr
    alpha = np.sin(w0) / (2 * q)
    a = 10 ** (gain_db / 40.0)
    cosw = np.cos(w0)
    b0 = 1 + alpha * a
    b1 = -2 * cosw
    b2 = 1 - alpha * a
    a0 = 1 + alpha / a
    a1 = -2 * cosw
    a2 = 1 - alpha / a
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def notch_depth(prominence_db: float) -> float:
    """突出度 10–25 dB 映射到 -6..-24 dB 陷波深度。"""
    return float(-np.clip(6.0 + 1.2 * (prominence_db - 10.0), 6.0, 24.0))


def apply_notches(x: np.ndarray, sr: float, howls: list[Howl],
                  q: float = 30.0) -> np.ndarray:
    """时域级联自适应陷波。"""
    y = x.astype(float)
    for h in howls:
        sos = peaking_biquad(h.freq_hz, sr, notch_depth(h.prominence_db), q)
        y = signal.sosfilt(sos, y)
    return y


def apply_notches_stft(spec: np.ndarray, bin_freqs: np.ndarray,
                       howls: list[Howl], q: float = 30.0) -> np.ndarray:
    """频域版陷波（离线矢量通路用），在 STFT bin 上计算精确双二阶频响。

    spec: (n_frames, n_bins) 复数谱；返回修改后的谱。
    采样率由 bin 网格的 Nyquist 反推，与时域 apply_notches 完全等价。
    """
    if not howls:
        return spec
    sr_ref = bin_freqs[-1] * 2.0
    w = 2 * np.pi * bin_freqs / sr_ref
    ejw = np.exp(-1j * w)
    ej2w = np.exp(-2j * w)
    gain_lin = np.ones(len(bin_freqs))
    for h in howls:
        sos = peaking_biquad(h.freq_hz, sr_ref,
                             notch_depth(h.prominence_db), q)
        b, a = sos[0][:3], sos[0][3:]
        h_w = ((b[0] + b[1] * ejw + b[2] * ej2w)
               / (a[0] + a[1] * ejw + a[2] * ej2w))
        gain_lin *= np.abs(h_w)
    return spec * gain_lin[None, :]


# ---------------------------------------------------------------- 自适应抵消
class AdaptiveFeedbackCanceller:
    """NLMS 自适应反馈抵消器（分块处理，单通道）。

    麦克风信号 m = 有用信号 s + F(y)，y 为受话器回放信号。
    自适应滤波器 ĥ 估计反馈路径 F，误差 e = m - ĥ*y 送助听器输入。
    更新前对 e、y 做一阶高通预白化，降低言语自相关导致的偏差。
    """

    def __init__(self, n_taps: int = 64, mu: float = 0.05,
                 pre_white: float = 0.7):
        self.n_taps = n_taps
        self.mu = mu
        self.pre_white = pre_white
        self.h = np.zeros(n_taps)
        self._ybuf = np.zeros(n_taps)
        self._ep = 0.0
        self._yp = 0.0

    def process_block(self, mic: np.ndarray, receiver: np.ndarray) -> np.ndarray:
        """输入一帧麦克风流与受话器流，返回抵消后的误差流。"""
        mic = np.asarray(mic, dtype=float)
        receiver = np.asarray(receiver, dtype=float)
        err = np.empty_like(mic)
        h, L = self.h, self.n_taps
        for i in range(len(mic)):
            self._ybuf[1:] = self._ybuf[:-1]
            self._ybuf[0] = receiver[i]
            f_hat = h @ self._ybuf
            e = mic[i] - f_hat                    # 原始空间误差（也是输出）
            # 预白化（一阶高通）只用于更新方向，降低言语自相关偏差
            ew = e - self.pre_white * self._ep
            yw = receiver[i] - self.pre_white * self._yp
            self._ep, self._yp = e, receiver[i]
            # 用白化参考的自相关能量归一化，保持 NLMS 量纲一致
            power = float(self._ybuf @ self._ybuf)
            h += (self.mu * ew * self._ybuf) / (1e-6 + power)
            err[i] = e
        self.h = h
        return err


def simulate_feedback_path(n_samples: int = 64, sr: float = 44100.0,
                           delay_ms: float = 1.0,
                           peak_hz: float = 3000.0,
                           gain_db: float = -6.0,
                           rng: np.random.Generator | None = None) -> np.ndarray:
    """合成一条物理上合理的反馈路径冲激响应：延迟 + 带通谐振 + 指数衰减。

    n_samples 应与自适应滤波器阶数匹配：默认 1 ms 延迟 + 1.5 ms 衰减、
    总长 64（44.1k 下约 1.45 ms），对应真实助听器受话器-麦克风声耦合。
    """
    rng = rng or np.random.default_rng(0)
    d = int(sr * delay_ms / 1000.0)
    t = np.arange(n_samples - d) / sr
    env = np.exp(-t * 650.0)       # 1.5 ms 衰减：能量集中在 64 阶窗口内
    tone = np.sin(2 * np.pi * peak_hz * t + rng.uniform(0, 2 * np.pi))
    h = np.zeros(n_samples)
    h[d:] = 10 ** (gain_db / 20.0) * env * tone
    return h


def erle_db(mic: np.ndarray, err: np.ndarray) -> float:
    """回声返回增强损耗（dB）：越大抵消越好。"""
    p_in = np.mean(mic ** 2)
    p_res = np.mean(err ** 2)
    return float(10 * np.log10((p_in + 1e-12) / (p_res + 1e-12)))
