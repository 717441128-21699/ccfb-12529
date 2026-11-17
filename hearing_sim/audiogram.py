"""听力图（audiogram）数据结构与常见预设。

听力阈值 HL 单位 dB HL，频率单位 Hz。标准测听频率覆盖 125–8000 Hz。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STD_FREQS = np.array([125, 250, 500, 1000, 2000, 3000, 4000, 6000, 8000], dtype=float)

# 老年听损中心常见的几类典型听力图（dB HL，左右耳相同）
PRESETS: dict[str, np.ndarray] = {
    "正常听力": np.array([5, 5, 8, 8, 10, 12, 12, 15, 15], dtype=float),
    "轻度老年性聋(高频缓降)": np.array([10, 12, 15, 20, 30, 40, 48, 55, 60], dtype=float),
    "中度平坦型": np.array([45, 45, 48, 50, 52, 52, 55, 55, 58], dtype=float),
    "中重度高频陡降": np.array([20, 25, 35, 45, 60, 70, 78, 85, 90], dtype=float),
    "重度平坦型": np.array([70, 72, 75, 78, 80, 82, 85, 88, 90], dtype=float),
}


@dataclass
class Audiogram:
    """单场测听的听力图，左右耳各一条阈值曲线。"""

    freqs: np.ndarray
    left_hl: np.ndarray
    right_hl: np.ndarray

    def __post_init__(self) -> None:
        self.freqs = np.asarray(self.freqs, dtype=float)
        self.left_hl = np.asarray(self.left_hl, dtype=float)
        self.right_hl = np.asarray(self.right_hl, dtype=float)
        if not (self.freqs.shape == self.left_hl.shape == self.right_hl.shape):
            raise ValueError("频率与左右耳阈值数组长度必须一致")
        if np.any(self.left_hl < 0) or np.any(self.right_hl < 0):
            raise ValueError("听阈不能为负值")

    @classmethod
    def from_preset(cls, name: str) -> "Audiogram":
        if name not in PRESETS:
            raise KeyError(f"未知预设: {name}，可选: {list(PRESETS)}")
        hl = PRESETS[name]
        return cls(STD_FREQS.copy(), hl.copy(), hl.copy())

    @classmethod
    def mono(cls, hl: np.ndarray, freqs: np.ndarray | None = None) -> "Audiogram":
        """单耳演示用：左右耳填同一条曲线。"""
        hl = np.asarray(hl, dtype=float)
        f = STD_FREQS.copy() if freqs is None else np.asarray(freqs, dtype=float)
        return cls(f, hl.copy(), hl.copy())

    def thresholds(self, ear: str = "left") -> np.ndarray:
        if ear == "left":
            return self.left_hl
        if ear == "right":
            return self.right_hl
        raise ValueError("ear 只能是 'left' 或 'right'")

    def interp_hl(self, target_freqs: np.ndarray, ear: str = "left") -> np.ndarray:
        """在 log2 频率轴上线性插值听阈，范围外取端点值，裁剪到 [0, 120] dB HL。"""
        hl = self.thresholds(ear)
        log_x = np.log2(self.freqs)
        # STFT 的 0 Hz bin 不能取对数，映射到最低测听频率
        safe = np.maximum(np.asarray(target_freqs, dtype=float), self.freqs[0])
        log_q = np.log2(safe)
        out = np.interp(log_q, log_x, hl)
        return np.clip(out, 0.0, 120.0)

    def three_freq_average(self, ear: str = "left") -> float:
        """500/1000/2000 Hz 三频平均听阈（NAL-R 等公式的输入 X）。"""
        return float(np.mean(self.interp_hl([500.0, 1000.0, 2000.0], ear)))
