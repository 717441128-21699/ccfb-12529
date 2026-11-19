"""频谱展宽 —— 模拟耳蜗性聋的频率分辨力下降。

Baer & Moore (1993) 方法: 在 STFT 幅度谱上沿频率轴做高斯卷积,
等效把每个听觉滤波器 (ERB) 的带宽展宽 factor 倍, 相位保持不变后重构。

ERB(f) = 24.7 * (4.37 f / 1000 + 1)            (Glasberg & Moore 1990)
sigma(f) = factor(f) * ERB(f) / 2

展宽因子按各频率听阈映射 (Nejime & Moore 1997 的临床演示惯例):
    HL <= 20 dB HL -> 1 (无展宽)
    HL >= 80 dB HL -> 6 (重度, 言语几乎不可分辨)
    之间线性。高频损失越重, 峰谷被抹平得越厉害 —— 这正是"声音听得见但
    听不清"的机制, 单纯衰减无法复现。
"""
from __future__ import annotations

import numpy as np

from .audiogram import Audiogram


def erb_hz(freq_hz: np.ndarray | float) -> np.ndarray:
    """Glasberg-Moore 等效矩形带宽 (Hz)。"""
    return 24.7 * (4.37 * np.asarray(freq_hz, float) / 1000.0 + 1.0)


def smearing_factors(audiogram: Audiogram, freqs: np.ndarray) -> np.ndarray:
    """由听阈计算各频率的展宽因子 (1..6)。"""
    hl = audiogram.interpolate(freqs)
    factor = 1.0 + 5.0 * np.clip((hl - 20.0) / 60.0, 0.0, 1.0)
    return factor


def smearing_matrix(freqs: np.ndarray, factors: np.ndarray) -> np.ndarray:
    """构造 (F, F) 高斯展宽矩阵, 每行归一化 (保持总能量)。"""
    f = np.asarray(freqs, float)
    sigma = np.asarray(factors, float) * erb_hz(f) / 2.0
    sigma = np.maximum(sigma, np.diff(f, prepend=f[0] - (f[1] - f[0])))
    # 距离超过 3 sigma 的贡献可忽略, 用截断控制计算量
    d = f[None, :] - f[:, None]                      # (target, source)
    s = sigma[:, None]
    weight = np.exp(-0.5 * (d / s) ** 2)
    weight[np.abs(d) > 3.0 * s] = 0.0
    weight /= weight.sum(axis=1, keepdims=True)
    return weight


def smear_magnitude(mag: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """对幅度谱 (frames, bins) 应用展宽矩阵。"""
    return mag @ matrix.T
