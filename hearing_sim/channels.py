"""8 通道分频带定义。

带边按近似对数间隔取在测听频率上，通道中心频率为相邻带边的几何平均，
便于把处方公式的目标值直接算在中心频率上。
"""
from __future__ import annotations

import numpy as np

NUM_CHANNELS = 8

# 8 个通道 → 9 条带边（Hz）
BAND_EDGES = np.array([125, 250, 500, 1000, 2000, 3000, 4000, 6000, 8000], dtype=float)


def band_centers(edges: np.ndarray = BAND_EDGES) -> np.ndarray:
    """几何平均中心频率。"""
    edges = np.asarray(edges, dtype=float)
    return np.sqrt(edges[:-1] * edges[1:])


def assign_bins(bin_freqs: np.ndarray, edges: np.ndarray = BAND_EDGES) -> np.ndarray:
    """把 STFT 频率 bin 映射到通道编号。

    低于最低带边的 bin 归入第 0 通道，高于最高带边的归入最后一个通道。
    """
    bin_freqs = np.asarray(bin_freqs, dtype=float)
    idx = np.searchsorted(edges, bin_freqs, side="right") - 1
    return np.clip(idx, 0, len(edges) - 2)
