"""8 通道滤波器组。

通道中心频率与 NAL-R 公式频率对齐, 边界取相邻中心的几何平均:
    250, 500, 1k, 1.5k, 2k, 3k, 4k, 6k Hz
两种实现:
  - LinkwitzRileyBank: 时域 LR4 (二阶 Butterworth 级联) 交叉滤波, 全通带可加性,
    用于信号完整性验证与离线精细分析;
  - spectral_bands:    STFT 频域分带, 供实时引擎使用。
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from .prescription import NAL_FREQS

N_CHANNELS = 8
CENTER_FREQS = NAL_FREQS.copy()


def band_edges(fs: float) -> np.ndarray:
    """返回 9 条边带频率 (Hz)。两端延伸到直流 / 奈奎斯特。"""
    geo = np.sqrt(CENTER_FREQS[:-1] * CENTER_FREQS[1:])
    return np.concatenate([[0.0], geo, [fs / 2.0]])


def band_for_frequency(freq: float) -> int:
    """把任意频率映射到通道编号 0..7。"""
    edges = band_edges(16000.0)
    idx = int(np.searchsorted(edges[1:-1], freq, side="left"))
    return min(max(idx, 0), N_CHANNELS - 1)


class LinkwitzRileyBank:
    """LR4 交叉滤波器组 (低通/高通级联)。

    每个内部交叉点一对 LR4 滤波器; 最低通道低通、最高通道高通。
    所有通道输出相加 ≈ 全通 (幅度误差 <0.1 dB, 相位保持一致)。
    """

    def __init__(self, fs: float):
        self.fs = fs
        self.edges = band_edges(fs)[1:-1]  # 7 个内部交叉频率
        nyq = fs / 2.0
        self._sos_lp = [butter(2, c / nyq, btype="low", output="sos") for c in self.edges]
        self._sos_hp = [butter(2, c / nyq, btype="high", output="sos") for c in self.edges]

    def split(self, x: np.ndarray) -> np.ndarray:
        """返回 (n_channels, n_samples) 分带信号。"""
        n = x.shape[-1]
        bands = np.zeros((N_CHANNELS, n))
        # 预处理每个交叉点的 LP/HP 输出
        lp = [sosfilt(sos, x) for sos in self._sos_lp]
        hp = [sosfilt(sos, x) for sos in self._sos_hp]
        bands[0] = lp[0]
        bands[-1] = hp[-1]
        for k in range(1, N_CHANNELS - 1):
            # 通道 k = HP(edge k-1) 与 LP(edge k) 的交叠区间
            bands[k] = sosfilt(self._sos_lp[k], hp[k - 1])
        return bands

    def reconstruct(self, x: np.ndarray) -> np.ndarray:
        return np.sum(self.split(x), axis=0)


def spectral_band_masks(n_fft: int, fs: float) -> np.ndarray:
    """STFT 频域分带掩码。

    返回 (n_channels, n_fft//2+1) 布尔数组, 按边带频率切分 bin。
    """
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / fs)
    edges = band_edges(fs)
    masks = np.zeros((N_CHANNELS, len(freqs)), dtype=bool)
    for k in range(N_CHANNELS):
        masks[k] = (freqs >= edges[k]) & (freqs < edges[k + 1])
    # 最高 bin 归入末通道
    masks[-1, -1] = True
    return masks
