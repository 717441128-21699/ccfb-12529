"""公开处方公式：NAL-R / NAL-RP / POGO（含 POGO-II）。

输出均为插入增益目标（insertion gain, dB），即相对于裸耳声场、
助听器在该频率应提供的增益。NAL 目标对应 65 dB SPL 平均言语输入。

参考
----
Byrne, D. & Dillon, H. (1986). The National Acoustic Laboratories' (NAL)
new procedure for selecting the gain and frequency response of a hearing
aid. Ear and Hearing, 7(4), 257-265.
Dillon, H. (2012). Hearing Aids (2nd ed.). Thieme. （NAL-RP 修正）
McCandless & Lyregaard (1983). POGO 处方公式。
"""

from __future__ import annotations

import numpy as np

from .audiogram import Audiogram

# NAL-R 公式覆盖的标准频率点（Hz）
NAL_FREQS = np.array([250.0, 500.0, 1000.0, 1500.0, 2000.0, 3000.0, 4000.0,
                      6000.0, 8000.0])
# X 为加权平均听损（dB HL）
NAL_WEIGHTS = {500: 0.15, 1000: 0.31, 2000: 0.20, 3000: 0.20, 4000: 0.14}
# 各频点插入增益 = X + 偏置（Byrne & Dillon 1986 原文表 2）
NAL_OFFSETS = {
    250: -17, 500: -8, 1000: -3, 1500: 1, 2000: -1,
    3000: -1, 4000: -2, 6000: -2, 8000: -5,   # 6k/8k 为手册常用延拓
}

# NAL-RP 重度/极重度损失修正的线性化系数（Dillon 2012 表 10.2 附近）：
# 仅当 PTA(500/1k/2k) > 60 dB HL 时启用，低频增补、2kHz 以上略减。
NAL_RP_CORRECTION = {
    250: 0.10, 500: 0.06, 1000: 0.02, 1500: 0.0,
    2000: -0.02, 3000: -0.03, 4000: -0.04, 6000: -0.04, 8000: -0.04,
}

POGO_FREQS = np.array([250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0])


def _nal_x(audiogram: Audiogram) -> float:
    hl = audiogram.hl_at(list(NAL_WEIGHTS.keys()))
    return float(sum(w * h for w, h in zip(NAL_WEIGHTS.values(), hl)))


def nal_r(audiogram: Audiogram, query_freqs=None) -> tuple[np.ndarray, np.ndarray]:
    """NAL-R 插入增益目标。返回 (频率, 增益dB)。"""
    x = _nal_x(audiogram)
    base = np.array([x + NAL_OFFSETS[int(f)] for f in NAL_FREQS])
    base = np.maximum(base, 0.0)
    if query_freqs is None:
        return NAL_FREQS.copy(), base
    q = np.asarray(query_freqs, dtype=float)
    return q, np.interp(np.log10(q), np.log10(NAL_FREQS), base)


def nal_rp(audiogram: Audiogram, query_freqs=None) -> tuple[np.ndarray, np.ndarray]:
    """NAL-RP：NAL-R 基础上对重度损失做低频增补、高频微减。"""
    freqs, gain = nal_r(audiogram)
    excess = max(0.0, audiogram.pta() - 60.0)
    if excess > 0:
        corr = np.array([NAL_RP_CORRECTION[int(f)] * excess for f in freqs])
        gain = np.maximum(gain + corr, 0.0)
    if query_freqs is None:
        return freqs, gain
    q = np.asarray(query_freqs, dtype=float)
    return q, np.interp(np.log10(q), np.log10(freqs), gain)


def pogo(audiogram: Audiogram, query_freqs=None,
         pogo2: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """POGO 插入增益目标。

    1000 Hz 以下 IG = 0.5 * HL，以上 IG = 0.75 * HL；
    250 Hz 再减 10 dB。POGO-II 对 >65 dB HL 的部分再补一半增益。
    """
    hl = audiogram.hl_at(POGO_FREQS)
    factor = np.where(POGO_FREQS < 1000.0, 0.5, 0.75)
    gain = factor * hl
    gain[POGO_FREQS == 250.0] -= 10.0
    if pogo2:
        gain += 0.5 * np.maximum(hl - 65.0, 0.0)
    gain = np.maximum(gain, 0.0)
    if query_freqs is None:
        return POGO_FREQS.copy(), gain
    q = np.asarray(query_freqs, dtype=float)
    return q, np.interp(np.log10(q), np.log10(POGO_FREQS), gain)


_FORMULAS = {"nal-r": nal_r, "nal-rp": nal_rp, "pogo": pogo}


def target_gain(audiogram: Audiogram, query_freqs,
                formula: str = "nal-r") -> np.ndarray:
    """按名称取处方公式在指定频率的插入增益目标（dB）。"""
    key = formula.lower()
    if key not in _FORMULAS:
        raise ValueError(f"未知处方公式 {formula}，可选 {list(_FORMULAS)}")
    _, g = _FORMULAS[key](audiogram, query_freqs)
    return g
