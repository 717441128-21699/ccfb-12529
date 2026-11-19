"""耳模/耳塞泄漏建模与低频增益自动补偿。

物理模型
--------
通气孔 (vent) 或开放耳塞对耳道内的接收器声构成二阶高通泄漏通路
(Keidser et al. 1999; Kuk & Keidser 2006 的开放耳响应形态):

    |H_vent(f)| = r^2 / sqrt(1 + r^4),  r = f / fc

开放耳塞 (open dome): fc ≈ 500 Hz, 低频几乎全漏;
封闭耳模 (closed, 小通气孔): fc ≈ 150 Hz, 仅极低频受影响。

有效真耳增益 = 处方目标增益 + 20log10|H_vent| (dB, 恒为负)。
补偿策略: 在反馈稳定余量 (feedback margin) 允许范围内, 把漏掉的增益补回去;
超过余量的部分作为残余泄漏返回给界面提示 —— 开放耳 250 Hz 通常无法补满,
这正是临床开放验配的真实限制。
"""
from __future__ import annotations

import numpy as np

FITTING_OPEN = "open"
FITTING_CLOSED = "closed"

# 两种验配形式的泄漏高通截止频率 (Hz)
VENT_FC = {FITTING_OPEN: 500.0, FITTING_CLOSED: 150.0}
DEFAULT_FEEDBACK_MARGIN = 6.0  # 允许追加的最大补偿增益 (dB)


def vent_response_db(freqs: np.ndarray | list[float], fitting: str = FITTING_OPEN) -> np.ndarray:
    """泄漏通路幅度响应 (dB, <=0)。"""
    if fitting not in VENT_FC:
        raise ValueError(f"fitting 必须是 {FITTING_OPEN!r} 或 {FITTING_CLOSED!r}")
    freqs = np.asarray(freqs, float)
    r = freqs / VENT_FC[fitting]
    mag = r**2 / np.sqrt(1.0 + r**4)
    # 直流保护
    mag = np.where(freqs <= 0, 1e-6, mag)
    return 20.0 * np.log10(np.maximum(mag, 1e-6))


def compensate_gains(
    target_gains_db: np.ndarray,
    freqs: np.ndarray,
    fitting: str = FITTING_OPEN,
    feedback_margin: float = DEFAULT_FEEDBACK_MARGIN,
) -> dict:
    """按验配形式自动补偿低频泄漏。

    Returns
    -------
    dict:
      vent_loss_db      泄漏衰减量 (正值 dB)
      compensation_db   实际追加的补偿 (dB)
      compensated_gains 补偿后的通道增益
      residual_loss_db  受反馈余量限制无法补回的残余泄漏
      stable            全部通道是否补满 (无残余泄漏)
    """
    freqs = np.asarray(freqs, float)
    vent_db = vent_response_db(freqs, fitting)
    vent_loss = -vent_db  # 正值
    comp = np.minimum(vent_loss, feedback_margin)
    compensated = np.asarray(target_gains_db, float) + comp
    residual = vent_loss - comp
    return {
        "fitting": fitting,
        "vent_fc_hz": VENT_FC[fitting],
        "vent_loss_db": vent_loss,
        "compensation_db": comp,
        "compensated_gains": compensated,
        "residual_loss_db": residual,
        "stable": bool(np.all(residual < 0.5)),
    }
