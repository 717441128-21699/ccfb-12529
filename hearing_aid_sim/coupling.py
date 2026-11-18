"""耳模耦合：开放/封闭耳模的低频漏音（插入损失）模型与自动补偿。

物理模型（Dillon 2012, Hearing Aids, vent 章节的工程化近似）
============================================================
通气孔对耳道声压表现为一阶高通（低频从孔中漏掉）：

    IL(f) = IL_max * fc^2 / (f^2 + fc^2)          （dB，正值=漏走的增益）

f << fc 时 IL 趋近 IL_max（低频几乎全漏），f >> fc 时 IL 趋近 0
（高频由声管正常送入）。封闭耳模 fc≈120 Hz、IL_max≈6 dB（仅微小缝隙），
开放耳模 fc≈600–800 Hz、IL_max≈16 dB。
要让实际到达鼓膜的插入增益达标，处方目标需加上 IL(f) 作为补偿，
再由两道物理约束截断：

1. 稳定裕量：靠近啸叫频点的频段补偿按 FEEDBACK_GUARD_DB 削减；
2. 上限 MAX_VENT_COMP_DB：避免过度增益诱发啸叫。
"""

from __future__ import annotations

import numpy as np

from .config import COUPLING_PRESETS, FEEDBACK_GUARD_DB, MAX_VENT_COMP_DB


def insertion_loss(freqs, preset: str = "open",
                   vent_corner_hz: float | None = None,
                   il_max: float | None = None) -> np.ndarray:
    """通气孔造成的低频插入损失（dB，正数）。"""
    cfg = COUPLING_PRESETS.get(preset)
    if cfg is None and vent_corner_hz is None:
        raise ValueError(f"未知耳模预设 {preset}")
    fc = vent_corner_hz if vent_corner_hz is not None else cfg["vent_corner_hz"]
    if il_max is None:
        il_max = 16.0 if preset == "open" else 6.0
    f = np.asarray(freqs, dtype=float)
    return il_max * fc**2 / (f**2 + fc**2)


def vent_compensation(freqs, preset: str = "open",
                      howl_freqs=(), howl_q: float = 1.5,
                      vent_corner_hz: float | None = None,
                      il_max: float | None = None) -> np.ndarray:
    """各频率应追加的漏音补偿增益（dB，非负）。

    howl_freqs 给出已检出的啸叫频点，其附近按一个倍频程宽度
    线性削减稳定裕量，防止"补漏音反而诱发啸叫"。
    """
    il = insertion_loss(freqs, preset, vent_corner_hz, il_max)
    guard = np.ones_like(il)
    for hf in np.atleast_1d(np.asarray(howl_freqs, dtype=float)):
        if hf <= 0:
            continue
        # 距啸叫点的对数倍频程距离；1 个倍频程内线性削减
        dist = np.abs(np.log2(np.asarray(freqs, dtype=float) / hf))
        guard = np.minimum(guard, np.clip(dist / howl_q, 0.0, 1.0))
    comp = il * guard
    return np.minimum(comp, MAX_VENT_COMP_DB)


def compensated_targets(target_db, freqs, preset: str = "open",
                        howl_freqs=(),
                        vent_corner_hz: float | None = None,
                        il_max: float | None = None) -> np.ndarray:
    """处方目标 + 漏音自动补偿，返回最终通道目标增益。"""
    comp = vent_compensation(freqs, preset, howl_freqs,
                             vent_corner_hz=vent_corner_hz, il_max=il_max)
    return np.asarray(target_db, dtype=float) + comp
