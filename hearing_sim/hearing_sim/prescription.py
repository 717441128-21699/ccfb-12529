"""公开处方公式。

实现内容
--------
1. NAL-R  (Byrne & Dillon, 1986): 线性处方, 65 dB SPL 输入的真耳插入增益 (REIG)。
2. NAL-RP (Byrne, Parkinson & Kilpatrick, 1991): NAL-R 的斜坡修正版,
   对陡降型听力损失削减 250/500 Hz 低频增益 (掩蔽规避)。
3. 响度归一化 WDRC (DSL 风格, Cornelisse et al. 1995): 把正常耳的响度区间
   [正常听阈, 100 dB HL] 线性映射到受损耳 [受损听阈, 不舒适阈 LDL],
   得到 50/65/80 dB SPL 三档输入目标增益, 供轻声/大声分开压缩使用。

NAL-R 方程 (f 单位 Hz, H_f 为该频率听阈 dB HL):
    X   = 0.05 * mean(H_500, H_1000, H_2000)
    IG  = C_f + 0.31 * H_f + X
频率常数 C_f:
    250:-17  500:-8  1000:+1  1500:+1  2000:-1  3000:-2  4000:-2  6000:-2

NAL-RP 斜坡修正 (仅作用于 250/500 Hz):
    C_slope = 0.06 * (mean(H_2000, H_3000, H_4000) - X)
    IG_250 -= C_slope ; IG_500 -= C_slope
重度 (>90 dB HL) 低频输出由 compressor 的 OSPL90 天花板限制。
"""
from __future__ import annotations

import numpy as np

from .audiogram import Audiogram, RETSPL

# NAL-R 公式覆盖的 8 个频率 (Hz), 同时也是本系统 8 通道的中心频率
NAL_FREQS = np.array([250.0, 500.0, 1000.0, 1500.0, 2000.0, 3000.0, 4000.0, 6000.0])
NAL_CONST = np.array([-17.0, -8.0, 1.0, 1.0, -1.0, -2.0, -2.0, -2.0])

# WDRC 目标曲线的输入声级锚点 (dB SPL)
WDRC_LEVELS = np.array([40.0, 50.0, 65.0, 80.0, 90.0, 100.0])
DEFAULT_LDL_HL = 100.0  # 未测量不舒适阈时的临床默认值 (dB HL)


def _hl_at(audiogram: Audiogram, freqs: np.ndarray) -> np.ndarray:
    return audiogram.interpolate(freqs)


def nalr_gains(audiogram: Audiogram) -> np.ndarray:
    """NAL-R 插入增益 (dB), 长度 8, 对应 NAL_FREQS, 输入 65 dB SPL。"""
    h = _hl_at(audiogram, NAL_FREQS)
    x = 0.05 * np.mean(audiogram.interpolate([500.0, 1000.0, 2000.0]))
    return NAL_CONST + 0.31 * h + x


def nalrp_gains(audiogram: Audiogram) -> np.ndarray:
    """NAL-RP 插入增益 (dB), 长度 8。"""
    g = nalr_gains(audiogram)
    x = 0.05 * np.mean(audiogram.interpolate([500.0, 1000.0, 2000.0]))
    hf_avg = np.mean(audiogram.interpolate([2000.0, 3000.0, 4000.0]))
    slope = 0.06 * (hf_avg - x)
    g[0] -= slope  # 250 Hz
    g[1] -= slope  # 500 Hz
    return g


def _retspl(freqs: np.ndarray) -> np.ndarray:
    return np.array([RETSPL.get(int(round(f)), 4.0) for f in freqs])


def wdrc_gains(
    audiogram: Audiogram,
    freqs: np.ndarray | None = None,
    input_levels: np.ndarray | None = None,
    ldl_hl: float = DEFAULT_LDL_HL,
    max_cr: float = 6.0,
) -> np.ndarray:
    """响度归一化 WDRC 目标增益 (dB)。

    Parameters
    ----------
    freqs : 评估频率, 默认 NAL_FREQS (8 通道中心)。
    input_levels : 输入声级锚点 dB SPL, 默认 WDRC_LEVELS。
    ldl_hl : 不舒适阈 (dB HL), 默认 100。

    Returns
    -------
    形状 (n_freq, n_level) 的增益表。正常耳响度区间
    [RETSPL, 100+RETSPL] 线性映射到受损耳 [H+RETSPL, LDL+RETSPL],
    压缩比 (输入:输出) = 100 / (LDL - H), 限制在 max_cr 以内。
    """
    if freqs is None:
        freqs = NAL_FREQS
    if input_levels is None:
        input_levels = WDRC_LEVELS
    freqs = np.asarray(freqs, float)
    levels = np.asarray(input_levels, float)

    h = _hl_at(audiogram, freqs)
    r = _retspl(freqs)
    t_normal = r                      # 正常听阈 SPL
    u_normal = 100.0 + r              # 正常不舒适阈 SPL
    t_imp = h + r                     # 受损听阈 SPL
    u_imp = ldl_hl + r                # 受损不舒适阈 SPL

    gains = np.empty((len(freqs), len(levels)))
    for i, level in enumerate(levels):
        # 线性响度映射, 分数位置按正常耳动态范围计算
        pos = np.clip((level - t_normal) / (u_normal - t_normal), 0.0, 1.0)
        out_spl = t_imp + (u_imp - t_imp) * pos
        gains[:, i] = out_spl - level

    # 压缩比限制: 受损动态范围不得小于 100/max_cr
    min_dr = 100.0 / max_cr
    dr = np.maximum(ldl_hl - h, min_dr)
    # 以 65 dB 为锚点重算 (受 max_cr 约束的版本)
    t_imp_eff = u_imp - dr
    for i, level in enumerate(levels):
        pos = np.clip((level - t_normal) / (u_normal - t_normal), 0.0, 1.0)
        out_spl = t_imp_eff + dr * pos
        gains[:, i] = out_spl - level
    return gains


def compression_ratios(audiogram: Audiogram, freqs: np.ndarray | None = None,
                       ldl_hl: float = DEFAULT_LDL_HL, max_cr: float = 6.0) -> np.ndarray:
    """各通道静态压缩比 (输入:输出, >=1)。"""
    if freqs is None:
        freqs = NAL_FREQS
    h = _hl_at(audiogram, np.asarray(freqs, float))
    dr = np.maximum(ldl_hl - h, 100.0 / max_cr)
    return 100.0 / dr


def prescription_targets(audiogram: Audiogram, formula: str = "NAL-R",
                         input_levels: np.ndarray | None = None) -> dict:
    """统一入口, 返回通道目标增益与元数据。

    Returns dict:
      formula, freqs, gains65 (n_freq,), gain_table (n_freq, n_level) 或 None,
      compression_ratios, ldl_spl (n_freq,)
    """
    formula = formula.upper()
    if formula == "NAL-R":
        g65 = nalr_gains(audiogram)
        table = None
    elif formula == "NAL-RP":
        g65 = nalrp_gains(audiogram)
        table = None
    elif formula in ("WDRC", "DSL-WDRC"):
        table = wdrc_gains(audiogram, NAL_FREQS, input_levels)
        g65 = table[:, list(WDRC_LEVELS).index(65.0)]
    else:
        raise ValueError(f"未知处方公式: {formula} (支持 NAL-R / NAL-RP / WDRC)")

    from .audiogram import RETSPL as _r
    ldl_spl = DEFAULT_LDL_HL + np.array([_r.get(int(round(f)), 4.0) for f in NAL_FREQS])
    return {
        "formula": formula,
        "freqs": NAL_FREQS.copy(),
        "gains65": g65,
        "gain_table": table,
        "input_levels": None if table is None else (input_levels or WDRC_LEVELS).copy(),
        "compression_ratios": compression_ratios(audiogram),
        "ldl_spl": ldl_spl,
    }
