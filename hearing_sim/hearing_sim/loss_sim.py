"""听力损失模拟 (助听前"老人现在听到的声音")。

采用 Clarity 项目 (Clarity Challenge, 2020-2023) 使用的耳蜗性聋可听化范式,
三层机制:

1. 阈下门限 (inaudibility):
   时频单元输入级 < 受损听阈 T(f) 时, 衰减 gate_atten_db (默认 30 dB),
   模拟"听不见"而非粗暴清零 (保留少量环境感)。

2. 响度重振 (recruitment) —— dB 域分段响度映射:
   - 阈下:            统一门限衰减;
   - 听阈~不舒适阈:   正常耳动态范围 100 dB 压缩到受损耳 (LDL - HL) 的窄范围,
                      压缩比 100/(LDL-HL), 听阈处起始、LDL 处封顶;
   - LDL 以上:        输出钳制在 LDL (模拟不舒适与限幅)。
   这样轻声被压低、正常语音被压窄、大声不再更响 —— 即"小声听不到、
   大声嫌吵"的重振现象, 且输出数学上有界。

3. 频谱展宽 (smearing 模块, Baer & Moore 1993):
   高频听损导致频率分辨力丧失, 言语峰谷被抹平 -> 听得见但听不清,
   这是需求 3 的关键, 单纯衰减无法复现。

参考电平: 0 dBFS = 94 dB SPL (校准常量, 可被 calibration 覆盖)。
"""
from __future__ import annotations

import numpy as np

from .audiogram import Audiogram, RETSPL
from .smearing import smearing_factors, smearing_matrix

CAL_DB_SPL = 94.0
GATE_ATTEN_DB = 30.0
NORMAL_DYNAMIC_RANGE = 100.0  # 正常耳 听阈->LDL 的动态范围 dB
DEFAULT_LDL_HL = 100.0


def power_exponents(audiogram: Audiogram, freqs: np.ndarray) -> np.ndarray:
    """各频率压缩指数 (0.2..1), 供时域幂律工具函数使用。"""
    hl = audiogram.interpolate(freqs)
    return np.clip(1.0 - hl / 60.0, 0.2, 1.0)


def power_law(x: np.ndarray, p: float) -> np.ndarray:
    """零记忆归一化幂律 (保留为工具函数; 引擎默认使用 dB 响度映射)。

    y = sign(x) * |x / x_ref|^p * x_ref, x_ref 为信号 RMS, 保证能量量级稳定。
    """
    x_ref = max(float(np.sqrt(np.mean(x**2))), 1e-8)
    return np.sign(x) * (np.abs(x) / x_ref) ** p * x_ref


def loudness_map_db(
    input_db_spl: np.ndarray,
    threshold_spl: np.ndarray,
    ldl_spl: np.ndarray,
    gate_atten_db: float = GATE_ATTEN_DB,
) -> np.ndarray:
    """dB 域重振响度映射, 返回输出级 (dB SPL), 形状与 input 相同。

    threshold_spl / ldl_spl 沿最后一个轴 (频率轴) 广播。
    """
    t = np.broadcast_to(threshold_spl, input_db_spl.shape)
    u = np.broadcast_to(ldl_spl, input_db_spl.shape)
    impaired_dr = np.maximum(u - t, 15.0)  # 防止极重度聋动态范围退化到 0
    cr = NORMAL_DYNAMIC_RANGE / impaired_dr

    out = np.empty_like(input_db_spl)
    below = input_db_spl < t
    above = input_db_spl >= u
    middle = ~(below | above)

    # 阈下: 输入再衰减固定门限量
    out[below] = input_db_spl[below] - gate_atten_db
    # 中间段: 从听阈起按受损动态范围线性增长
    out[middle] = t[middle] + (input_db_spl[middle] - t[middle]) / cr[middle]
    # LDL 以上: 钳制
    out[above] = u[above]
    return out


def apply_threshold_gate(
    magnitude_db_spl: np.ndarray,
    threshold_spl: np.ndarray,
    gate_atten_db: float = GATE_ATTEN_DB,
) -> np.ndarray:
    """对低于听阈的时频单元施加线性衰减因子 (兼容旧接口)。"""
    below = magnitude_db_spl < threshold_spl[None, :]
    factor = np.ones_like(magnitude_db_spl)
    factor[below] = 10.0 ** (-gate_atten_db / 20.0)
    return factor


def build_loss_parameters(audiogram: Audiogram, freqs: np.ndarray,
                          ldl_hl: float = DEFAULT_LDL_HL) -> dict:
    """预计算引擎所需的全部听损参数 (按 STFT bin 频率)。"""
    freqs = np.asarray(freqs, float)
    p = power_exponents(audiogram, freqs)
    retspl = np.array([RETSPL.get(int(round(f)), 4.0) for f in freqs])
    threshold_spl = audiogram.interpolate(freqs) + retspl
    ldl_spl = np.full_like(freqs, ldl_hl) + retspl
    factors = smearing_factors(audiogram, freqs)
    matrix = smearing_matrix(freqs, factors)
    return {
        "freqs": freqs,
        "power_exponents": p,
        "threshold_spl": threshold_spl,
        "ldl_spl": ldl_spl,
        "smear_matrix": matrix,
        "smear_factors": factors,
    }
