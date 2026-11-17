"""耳模气孔（vent）泄漏建模与低频自动补偿（验收指标 2）。

开放耳模（open dome）低频大量从气孔漏出，封闭耳模（custom mold）泄漏少。
把泄漏路径建模为一阶高通：

    H_vent(f) = j(f/fc) / (1 + j(f/fc))        （幅度响应）
    泄漏量 L(f) = -20*log10|H_vent(f)|  (dB)

所需补偿增益 = L(f)，再按通道汇总；为避免低频过补引发啸叫，单通道补偿
默认封顶 40 dB，并在返回结果里标记被封顶的通道。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import channels as ch_mod

# 两种耳模的默认气孔截止频率（Hz）与典型 2cc 耦合腔经验值一致
VENT_FC = {
    "open": 500.0,      # 开放式耳塞：低频泄漏大
    "closed": 150.0,    # 封闭式定制耳模：泄漏很小
}
MAX_COMPENSATION_DB = 40.0


@dataclass
class OcclusionResult:
    """泄漏补偿计算结果。"""

    mold_type: str
    fc_hz: float
    leakage_db: np.ndarray          # 每通道泄漏量（正值，dB）
    compensation_db: np.ndarray      # 实际施加的每通道补偿（dB）
    capped_channels: list[int]      # 达到补偿上限的通道编号
    bin_leakage_db: np.ndarray      # 每个 STFT bin 的泄漏量（绘图用）


def leakage_highpass_db(freqs: np.ndarray, fc_hz: float) -> np.ndarray:
    """一阶高通在各频率上的衰减量（正值 dB）。0 Hz 处给一个大有限值。"""
    freqs = np.asarray(freqs, dtype=float)
    with np.errstate(divide="ignore"):
        r = np.where(freqs > 0, freqs / fc_hz, 1e-9)
    mag = r / np.sqrt(1.0 + r**2)
    return -20.0 * np.log10(np.maximum(mag, 1e-6))


def compute_occlusion(bin_freqs: np.ndarray, mold_type: str = "open",
                      max_comp_db: float = MAX_COMPENSATION_DB) -> OcclusionResult:
    """计算耳模泄漏与每通道自动补偿增益。

    每通道泄漏量取该通道全部 STFT bin 的均值（而不是只看几何中心），
    这样最低频通道里 125 Hz 附近的大量泄漏也能被正确统计。
    """
    mold_type = mold_type.lower()
    if mold_type not in VENT_FC:
        raise ValueError(f"未知耳模类型 {mold_type}，可选: {list(VENT_FC)}")
    fc = VENT_FC[mold_type]

    bin_leak = leakage_highpass_db(bin_freqs, fc)
    centers = ch_mod.band_centers()
    center_leak = leakage_highpass_db(centers, fc)

    # 每通道平均泄漏（按 STFT bin 归属汇总）
    bin_channels = ch_mod.assign_bins(bin_freqs)
    band_leak = np.array([
        bin_leak[bin_channels == c].mean() if np.any(bin_channels == c)
        else center_leak[c]
        for c in range(ch_mod.NUM_CHANNELS)
    ])

    capped = [int(c) for c in np.where(band_leak > max_comp_db)[0]]
    comp = np.minimum(band_leak, max_comp_db)

    return OcclusionResult(
        mold_type=mold_type,
        fc_hz=fc,
        leakage_db=band_leak,
        compensation_db=comp,
        capped_channels=capped,
        bin_leakage_db=bin_leak,
    )
