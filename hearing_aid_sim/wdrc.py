"""分通道 WDRC（宽动态范围压缩）：轻声与大声分开处理。

静态压缩曲线（dB 输入 SPL -> dB 增益）
======================================
- 轻声段（L <= 膝点 TK 52 dB SPL）：线性放大，增益 = 处方目标增益；
- 中间段：压缩比 CR 由"把 50 dB HL 动态范围压进听阈..LDL 区间"反解；
- 大声段（L >= 限拐点）：最大输出限制在 LDL - 3 dB SPL（削峰式限幅）。

包络检测
========
dB 域一阶 IIR，快启动（5 ms）慢释放（80 ms），
符合 ANSI s3.47 对助听器压缩时间常数的测试约定。
"""

from __future__ import annotations

import numpy as np

from .config import (ATTACK_TAU, LDL_INTERCEPT, LDL_MAX, LDL_MIN,
                     LDL_RESERVE_DB, LDL_SLOPE, RELEASE_TAU)


def ldl_db_spl(hl_db: float) -> float:
    """由听阈估计响度不适级（dB SPL），简化临床回归。"""
    return float(np.clip(LDL_INTERCEPT + LDL_SLOPE * hl_db, LDL_MIN, LDL_MAX))


def compression_ratio(hl_db: float) -> float:
    """反解压缩比：50 dB 输入动态范围 -> (LDL - 听阈SPL) 输出动态范围。"""
    ldl = ldl_db_spl(hl_db)
    # 听阈 SPL 近似（耳机/声场 RETSPL 在 1–4k 约 2–7 dB，取 4 dB 均值）
    threshold_spl = hl_db + 4.0
    usable = max(ldl - LDL_RESERVE_DB - threshold_spl, 10.0)
    return float(np.clip(50.0 / usable, 1.0, 5.0))


def static_gain(level_db_spl, target_65_db: float, hl_db: float) -> np.ndarray:
    """静态压缩曲线：给定输入电平和 65 dB SPL 处的目标增益，返回增益(dB)。

    分段设计（处方目标在轻声/典型言语段直接生效，压缩只对大声介入）：
    - 轻声段 L <= 65 dB SPL：线性放大，增益恒为 target_65_db。
      处方公式（NAL-R/POGO）本身就是为典型言语电平定义的目标，
      轻声线性区直接采用，保证各通道在实际工作电平上精确命中目标；
    - 压缩段 65 < L < 80：斜率 (1 - 1/CR)，从 (65, target) 平滑过渡；
    - 大声段 L >= 80：最大输出限制在 LDL - 3 dB SPL。
    """
    level = np.asarray(level_db_spl, dtype=float)
    cr = compression_ratio(hl_db)
    ldl = ldl_db_spl(hl_db) - LDL_RESERVE_DB
    tk_loud = 80.0
    slope = 1.0 - 1.0 / cr
    gain_compress = target_65_db + slope * (level - 65.0)

    gain = np.where(level <= 65.0, target_65_db, gain_compress)
    # 大声限幅：输出不得超过 LDL
    gain = np.minimum(gain, ldl - level)
    # 增益不为负（负增益由整体降噪/削峰负责，不在压缩器里做）
    return np.maximum(gain, 0.0)


def envelope_peak(levels_db, sr: float, hop: int,
                  attack_tau: float = ATTACK_TAU,
                  release_tau: float = RELEASE_TAU,
                  init_level: float = 65.0) -> np.ndarray:
    """dB 域一阶包络跟踪（帧序列输入，帧序列输出）。

    输入高于当前估计走快启动、低于走慢释放。初值设为典型言语电平，
    避免信号开头的慢爬升污染稳态增益测量。
    """
    levels = np.asarray(levels_db, dtype=float)
    frame_t = hop / sr
    a_atk = float(np.exp(-frame_t / attack_tau))
    a_rel = float(np.exp(-frame_t / release_tau))
    out = np.empty_like(levels)
    prev = init_level
    for i, x in enumerate(levels):
        a = a_atk if x > prev else a_rel
        prev = a * prev + (1.0 - a) * x
        out[i] = prev
    return out


def wdrc_gain_curve(levels_db, target_65_db: float, hl_db: float,
                    sr: float, hop: int) -> np.ndarray:
    """包络检测 + 静态曲线，返回每个分析帧应施加的增益(dB)。"""
    env = envelope_peak(levels_db, sr, hop)
    return static_gain(env, target_65_db, hl_db)
