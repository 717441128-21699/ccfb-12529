"""听力图数据模型。

听力图以 dB HL 表示，频率可只给标准测听点（125–8000 Hz），
查询任意频率时在对数频率轴上做线性插值（dB 域）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import AUDIOGRAM_FREQS

HL_MIN, HL_MAX = -10.0, 120.0


@dataclass
class Audiogram:
    """单耳听力图。

    Parameters
    ----------
    freqs : array_like, Hz，升序
    hl    : array_like，对应频率的听阈 dB HL
    ear   : "left" | "right"，仅用于展示
    """

    freqs: np.ndarray
    hl: np.ndarray
    ear: str = "right"

    def __post_init__(self) -> None:
        self.freqs = np.asarray(self.freqs, dtype=float)
        self.hl = np.asarray(self.hl, dtype=float)
        if self.freqs.shape != self.hl.shape:
            raise ValueError("freqs 与 hl 长度必须一致")
        if self.freqs.ndim != 1 or len(self.freqs) < 2:
            raise ValueError("至少需要两个测听点")
        if np.any(np.diff(self.freqs) <= 0):
            raise ValueError("频率必须严格升序")
        if np.any(self.hl < HL_MIN) or np.any(self.hl > HL_MAX):
            raise ValueError(f"dB HL 应在 {HL_MIN}..{HL_MAX} 范围内")

    @classmethod
    def standard(cls, hl_values, ear: str = "right") -> "Audiogram":
        """用标准 9 点测听值构造（125..8000 Hz）。"""
        values = np.asarray(hl_values, dtype=float)
        if values.shape != AUDIOGRAM_FREQS.shape:
            raise ValueError(f"标准听力图需要 {len(AUDIOGRAM_FREQS)} 个点")
        return cls(AUDIOGRAM_FREQS.copy(), values, ear=ear)

    def hl_at(self, query_freqs) -> np.ndarray:
        """对数频率轴上的 dB 线性插值，区间外按端点值平坦延拓。"""
        f = np.asarray(query_freqs, dtype=float)
        return np.interp(np.log10(f), np.log10(self.freqs), self.hl)

    def pta(self) -> float:
        """三频纯音平均（500/1000/2000 Hz），dB HL。"""
        return float(np.mean(self.hl_at([500.0, 1000.0, 2000.0])))

    def degree(self) -> str:
        """按 WHO 常用分级（基于 PTA）。"""
        p = self.pta()
        if p < 25:
            return "正常"
        if p < 40:
            return "轻度"
        if p < 60:
            return "中度"
        if p < 80:
            return "重度"
        return "极重度"
