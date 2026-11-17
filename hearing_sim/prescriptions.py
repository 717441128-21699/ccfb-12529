"""公开处方公式与非线性压缩目标。

已实现的公开发表公式
--------------------
- NAL-R  (Byrne & Dillon, 1986)：线性插入增益，本系统默认公式，±3 dB 验收基准
- NAL-RP (Dillon, 2012 教材整理)：NAL-R 的重度听损修正版
- POGO   (McCandless & Lyregaard, 1983)：半增益定律
- FIG6   (Killion, 1995)：近全增益减固定修正量

所有公式给出的都是「插入增益目标」(dB)，即助听器相对裸耳在耳道处应增加的增益。
公式仅在 250–6000 Hz 有原始系数，超出范围按端点常数延伸（在结果与文档中注明）。
"""
from __future__ import annotations

import numpy as np

from .audiogram import Audiogram

# ---------------------------------------------------------------------------
# NAL-R 原始系数表（Byrne & Dillon 1986，Dillon《Hearing Aids》教材表 10.1）
# IG(f) = X + 0.31*HL(f) + a(f)
# X     = 0.15*HL500 + 0.31*HL1k + 0.54*HL2k
# ---------------------------------------------------------------------------
NAL_R_FREQS = np.array([250, 500, 1000, 1500, 2000, 3000, 4000, 6000], dtype=float)
NAL_R_A = np.array([-17, -8, 1, 1, -1, -2, -2, -2], dtype=float)
NAL_R_B = 0.31
NAL_R_X_WEIGHTS = {500: 0.15, 1000: 0.31, 2000: 0.54}

# POGO 固定修正量（dB），IG(f) = 0.5*HL(f) + c(f)
POGO_FREQS = np.array([250, 500, 1000, 2000, 3000, 4000, 6000], dtype=float)
POGO_C = np.array([-10, -5, 0, 0, 0, 0, 0], dtype=float)

# FIG6 固定修正量（dB），IG(f) = HL(f) + c(f)
FIG6_FREQS = np.array([250, 500, 1000, 2000, 3000, 4000, 6000], dtype=float)
FIG6_C = np.array([-25, -20, -15, -15, -17, -18, -24], dtype=float)

FORMULAS = ("NAL-R", "NAL-RP", "POGO", "FIG6")

# WDRC 三个标准锚定输入电平（dB SPL）
LEVEL_SOFT = 50.0
LEVEL_MEDIUM = 65.0
LEVEL_LOUD = 80.0


def _interp_const(freqs_table: np.ndarray, const_table: np.ndarray,
                  target_freqs: np.ndarray) -> np.ndarray:
    """log2 频率轴插值常数表，超出范围按端点延伸。"""
    return np.interp(
        np.log2(np.asarray(target_freqs, dtype=float)),
        np.log2(freqs_table),
        const_table,
    )


def nal_r_x(ag: Audiogram, ear: str = "left") -> float:
    """NAL-R 的加权三频项 X。"""
    hl = ag.interp_hl(list(NAL_R_X_WEIGHTS.keys()), ear)
    return float(sum(w * h for w, h in zip(NAL_R_X_WEIGHTS.values(), hl)))


def nal_r_targets(ag: Audiogram, target_freqs: np.ndarray,
                  ear: str = "left", profound_correction: bool = False) -> np.ndarray:
    """NAL-R（可选 NAL-RP 重度修正）插入增益目标。

    NAL-RP: 当 500/1k/2k 三频平均 > 60 dB HL 时，所有频率额外加
    0.2 * (H3FA - 60) dB（Dillon 教材 NAL-RP 规则）。
    """
    target_freqs = np.asarray(target_freqs, dtype=float)
    x = nal_r_x(ag, ear)
    hl = ag.interp_hl(target_freqs, ear)
    a = _interp_const(NAL_R_FREQS, NAL_R_A, target_freqs)
    gain = x + NAL_R_B * hl + a
    if profound_correction:
        h3fa = ag.three_freq_average(ear)
        gain = gain + 0.2 * max(0.0, h3fa - 60.0)
    return np.maximum(gain, 0.0)


def pogo_targets(ag: Audiogram, target_freqs: np.ndarray, ear: str = "left") -> np.ndarray:
    """原始 POGO 插入增益目标：半增益定律加低频减益。"""
    target_freqs = np.asarray(target_freqs, dtype=float)
    hl = ag.interp_hl(target_freqs, ear)
    c = _interp_const(POGO_FREQS, POGO_C, target_freqs)
    return np.maximum(0.5 * hl + c, 0.0)


def fig6_targets(ag: Audiogram, target_freqs: np.ndarray, ear: str = "left") -> np.ndarray:
    """FIG6 插入增益目标（适用于 20–60 dB HL 范围，结果下限截 0）。"""
    target_freqs = np.asarray(target_freqs, dtype=float)
    hl = ag.interp_hl(target_freqs, ear)
    c = _interp_const(FIG6_FREQS, FIG6_C, target_freqs)
    return np.maximum(hl + c, 0.0)


def linear_targets(ag: Audiogram, target_freqs: np.ndarray,
                   formula: str = "NAL-R", ear: str = "left") -> np.ndarray:
    """按名称返回线性处方公式的插入增益目标（dB）。"""
    if formula == "NAL-R":
        return nal_r_targets(ag, target_freqs, ear, profound_correction=False)
    if formula == "NAL-RP":
        return nal_r_targets(ag, target_freqs, ear, profound_correction=True)
    if formula == "POGO":
        return pogo_targets(ag, target_freqs, ear)
    if formula == "FIG6":
        return fig6_targets(ag, target_freqs, ear)
    raise ValueError(f"未知公式 {formula}，可选: {FORMULAS}")


def default_compression_ratios(hl_at_centers: np.ndarray) -> np.ndarray:
    """按听阈给默认压缩比：听损越重压缩比越大，限幅 1.6–3.5。

    CR = 1 + HL/60（HL=36 → 1.6，HL=90 → 2.5…），重听损通道再上浮。
    """
    hl = np.asarray(hl_at_centers, dtype=float)
    cr = 1.0 + hl / 60.0
    return np.clip(cr, 1.6, 3.5)


def wdrc_targets(ag: Audiogram, target_freqs: np.ndarray,
                 input_level_spl: float = LEVEL_MEDIUM,
                 formula: str = "NAL-R", ear: str = "left",
                 compression_ratios: np.ndarray | None = None,
                 max_gain_db: float = 75.0) -> np.ndarray:
    """非线性 WDRC 目标增益（dB）。

    以线性处方目标作为 65 dB SPL（中等输入）锚点，按各通道压缩比向
    轻声(50 dB SPL)/大声(80 dB SPL)两侧展开：

        G(L) = G(65) + (65 - L) * (1 - 1/CR)

    该式保证输出变化量 = 输入变化量 / CR，即真实压缩比为 CR。
    65 dB SPL 处与所选线性公式完全一致（±3 dB 验收点）。
    """
    target_freqs = np.asarray(target_freqs, dtype=float)
    g_medium = linear_targets(ag, target_freqs, formula, ear)
    if compression_ratios is None:
        compression_ratios = default_compression_ratios(
            ag.interp_hl(target_freqs, ear)
        )
    cr = np.clip(np.asarray(compression_ratios, dtype=float), 1.0, 10.0)
    offset = (LEVEL_MEDIUM - input_level_spl) * (1.0 - 1.0 / cr)
    return np.clip(g_medium + offset, -10.0, max_gain_db)
