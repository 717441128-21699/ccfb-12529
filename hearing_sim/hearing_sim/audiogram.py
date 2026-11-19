"""听力图数据模型。

标准气导听力图频率 (ANSI S3.6 临床常用 10 个点), 单位 dB HL。
提供对数频率轴上的线性插值, 范围外按平坦外推处理。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

import numpy as np

# 临床标准听力图频率 (Hz)
STD_FREQS = np.array([125, 250, 500, 1000, 1500, 2000, 3000, 4000, 6000, 8000], dtype=float)

# ANSI S3.6 参考等效阈值声压级 RETSPL (TDH 耳机近似值, dB SPL @ 0 dB HL)
RETSPL = {
    125: 26.0, 250: 14.0, 500: 6.0, 750: 2.0, 1000: 4.0, 1500: 2.0,
    2000: 0.0, 3000: -2.0, 4000: -2.0, 6000: 2.0, 8000: 6.0,
}


@dataclass
class Audiogram:
    """单耳听力图。

    Attributes
    ----------
    freqs : 频率数组 (Hz), 升序
    losses: 对应听阈 (dB HL), 数值越大损失越重
    ear   : "left" / "right"
    """

    freqs: np.ndarray
    losses: np.ndarray
    ear: str = "right"

    def __post_init__(self) -> None:
        self.freqs = np.asarray(self.freqs, dtype=float)
        self.losses = np.asarray(self.losses, dtype=float)
        order = np.argsort(self.freqs)
        self.freqs = self.freqs[order]
        self.losses = self.losses[order]
        if self.freqs.size < 2:
            raise ValueError("听力图至少需要 2 个频率点")
        if np.any(self.losses < -10) or np.any(self.losses > 120):
            raise ValueError("听阈 dB HL 应落在 -10 ~ 120 之间")

    # -- 插值 ---------------------------------------------------------------
    def interpolate(self, freqs: np.ndarray | list[float]) -> np.ndarray:
        """对数频率轴线性插值; 超出范围按最端点值平坦外推。"""
        freqs = np.asarray(freqs, dtype=float)
        log_x = np.log(self.freqs)
        log_q = np.log(np.clip(freqs, self.freqs[0], self.freqs[-1]))
        return np.interp(log_q, log_x, self.losses)

    def threshold_spl(self, freqs: np.ndarray | list[float]) -> np.ndarray:
        """返回给定频率的听阈声压级 (dB SPL)。"""
        hl = self.interpolate(freqs)
        retspl = np.array([RETSPL.get(int(round(f)), 4.0) for f in np.asarray(freqs, dtype=float)])
        return hl + retspl

    # -- 摘要指标 ------------------------------------------------------------
    @property
    def pta3(self) -> float:
        """500/1000/2000 Hz 平均听阈 (PTA)。"""
        return float(np.mean(self.interpolate([500, 1000, 2000])))

    @property
    def pta4(self) -> float:
        """500/1000/2000/4000 Hz 平均听阈。"""
        return float(np.mean(self.interpolate([500, 1000, 2000, 4000])))

    @property
    def severity(self) -> str:
        """WHO 听力损失分级 (按 PTA4)。"""
        p = self.pta4
        if p < 25:
            return "正常"
        if p < 40:
            return "轻度"
        if p < 60:
            return "中度"
        if p < 80:
            return "重度"
        return "极重度"

    # -- 序列化 --------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "ear": self.ear,
            "freqs": self.freqs.tolist(),
            "losses": self.losses.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Audiogram":
        return cls(np.asarray(d["freqs"], float), np.asarray(d["losses"], float), d.get("ear", "right"))

    @classmethod
    def standard(cls, losses: np.ndarray | list[float], ear: str = "right") -> "Audiogram":
        """用 STD_FREQS 十个标准频率点构造。"""
        if len(losses) != len(STD_FREQS):
            raise ValueError(f"需要 {len(STD_FREQS)} 个标准频率点")
        return cls(STD_FREQS.copy(), np.asarray(losses, float), ear)

    @classmethod
    def from_csv(cls, path: str, ear: str = "right") -> "Audiogram":
        """CSV 两列: frequency_hz, loss_dbhl (含表头)。"""
        freqs, losses = [], []
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                freqs.append(float(row["frequency_hz"]))
                losses.append(float(row["loss_dbhl"]))
        return cls(np.array(freqs), np.array(losses), ear)


# -- 常用示例听力图 -----------------------------------------------------------
def preset_flat40() -> Audiogram:
    """平坦型 40 dB HL (中度)。"""
    return Audiogram.standard([40] * 10)


def preset_presbycusis() -> Audiogram:
    """典型老年性聋: 低频正常、高频斜坡下降。"""
    return Audiogram.standard([15, 20, 25, 30, 40, 45, 55, 60, 70, 75])


def preset_steep_slope() -> Audiogram:
    """陡降型高频聋。"""
    return Audiogram.standard([10, 10, 15, 20, 35, 50, 65, 75, 85, 90])


def preset_normal() -> Audiogram:
    """正常听力。"""
    return Audiogram.standard([5, 5, 5, 5, 5, 5, 5, 5, 5, 5])
