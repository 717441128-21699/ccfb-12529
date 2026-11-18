"""裸耳听损模拟（"老人现在听到的版本"）。

三个独立机制，分别对应感音神经性听损的三个可感知后果
================================================================
1. 阈值抬升 + 响度重振（recruitment）
   听阈以下的频带直接静音（只保留低于听阈的内部底噪）；
   听阈以上，听损耳的响度增长比正常耳快（斜率 slope < 1），
   因此把信号向听阈方向压缩的线性增益为：
       gain_dB = (1/slope - 1) * (HL + RETSPL - L)
   轻声（L 接近听阈）衰减最大，大声（L 远高于听阈）衰减变小——
   可听动态范围被收窄，而不是简单地整体关小音量。

2. 频谱涂抹（spectral smearing）
   外毛细胞损伤使耳蜗频率选择性下降。在 32 个对数子带上做
   高斯功率扩散，扩散宽度随该频带听损变宽
   （正常耳约 0.15 oct，重度损失展宽到 0.55 oct）。
   效果：共振峰边界糊在一起，辅音（尤其高频擦音）可辨度下降。

3. 时间包络涂抹（temporal smearing）
   听力损失使时间精细结构与快速包络跟踪变差，对每个子带包络做
   低通平滑，时间常数随听损增大（最重约 40 ms），
   使短促辅音的起止（onset/offset）变钝。

参考：Baer & Moore (1993, 1994) 频谱涂抹模型；
Lorenzi 等关于时间包络与言语辨识的系列实验。
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from .audiogram import Audiogram
from .config import DEFAULT_CAL_DB_SPL, HOP
from .spectral import istft, stft, subband_membership

RETSPL_DB = 4.0          # 1–4 kHz 平均参考等效阈压级近似
INAUDIBLE_GAIN_DB = -35.0


def recruitment_slope(hl: np.ndarray) -> np.ndarray:
    """响度增长斜率：HL 越高斜率越小（增长越陡）。"""
    return np.clip(1.0 - 0.005 * hl, 0.55, 1.0)


def perceived_level(level_spl: np.ndarray, hl: np.ndarray) -> np.ndarray:
    """输入 SPL -> 听损耳内部响度级（dB 量纲坐标）。

    听阈以下返回听阈坐标 -10（标记为不可闻区域，不抛 NaN 便于比较）；
    听阈以上按重振斜率变陡增长：听损越重，同等输入的内部响度越低。
    """
    threshold = hl + RETSPL_DB
    slope = recruitment_slope(hl)
    p = threshold + (level_spl - threshold) / np.maximum(slope, 1e-3)
    return np.where(level_spl < threshold, threshold - 10.0, p)


def _gaussian_spreading_matrix(centers_hz: np.ndarray,
                               widths_oct: np.ndarray) -> np.ndarray:
    """子带功率扩散阵 S[i,j]：j 带功率泄漏到 i 带的比例（列归一化）。"""
    n = len(centers_hz)
    logc = np.log2(centers_hz)
    d = logc[None, :] - logc[:, None]                     # (i, j)
    sigma = np.broadcast_to(widths_oct[None, :], (n, n))
    s = np.exp(-0.5 * (d / sigma) ** 2)
    s /= np.maximum(s.sum(axis=0, keepdims=True), 1e-12)
    return s


def simulate_unaided(x: np.ndarray, sr: int, audiogram: Audiogram,
                     n_sub: int = 32,
                     add_threshold_noise: bool = True,
                     rng: np.random.Generator | None = None) -> np.ndarray:
    """生成裸耳听损模拟信号。

    Parameters
    ----------
    x : 单声道时域信号（-1..1）
    audiogram : 该耳听力图
    add_threshold_noise : 是否在不可闻频带叠加低电平内部噪声
                          （模拟听损耳的阈值底噪，电平固定低于听阈 8 dB）
    """
    rng = rng or np.random.default_rng(42)
    spec, bin_freqs, _ = stft(x, sr)
    membership, centers, _ = subband_membership(bin_freqs, n_sub=n_sub)
    hl_sub = audiogram.hl_at(centers)
    threshold_sub = hl_sub + RETSPL_DB

    # ---------- 1. 子带电平（dB SPL），换算与 spectral.band_levels 一致
    from scipy import signal as _signal
    from .config import N_FFT as _N_FFT, WINDOW as _WINDOW
    _win = _signal.get_window(_WINDOW, _N_FFT)
    scale = 2.0 / np.sum(_win ** 2)
    n_bins = spec.shape[1]
    onesided = np.full(n_bins, 2.0)
    onesided[0] = 1.0
    if n_bins > 1:
        onesided[-1] = 1.0
    power = np.maximum(np.abs(spec) ** 2, 1e-20) * onesided
    sub_power = power @ membership.T                    # (frames, n_sub)
    sub_count = np.maximum(membership.sum(axis=1), 1.0)
    sub_rms_power = sub_power * scale
    sub_spl = 10 * np.log10(sub_rms_power + 1e-20) + DEFAULT_CAL_DB_SPL - 3.01

    # ---------- 2. 重振增益（纯衰减映射）
    # 听损耳听阈 T=HL+RETSPL、LDL 约 100+0.35HL。模拟目标是让正常耳听到
    # "听损耳视角"的声音：
    #   - 听阈以下：静音（固定 INAUDIBLE_GAIN_DB）；
    #   - 听阈处：输出接近静音；
    #   - LDL 处：输出与正常耳响度趋同（增益趋近 0）；
    #   - 中间按重振斜率压缩：轻声衰减多、大声衰减少，动态范围收窄。
    # 线性插值增益（dB，全程 <=0）：
    #   gain = -(T-L) 映射到 [INAUDIBLE, 0]，用 slope 控制压缩曲率。
    slope = recruitment_slope(hl_sub)[None, :]                   # (1, n_sub)
    threshold = threshold_sub[None, :]
    inaudible = sub_spl < threshold
    # 可听区：超过听阈的余量 (L-T) 经 slope 压缩后，与原始余量的差即衰减量
    excess = np.maximum(sub_spl - threshold, 0.0)
    gain_db = slope * excess - excess            # = -(1-slope)*excess，恒 <=0
    gain_db = np.where(inaudible, INAUDIBLE_GAIN_DB, gain_db)

    # ---------- 3. 时间包络涂抹：对可闻帧的增益做低通（等效平滑包络）
    # tau 随 HL：0 ms(正常) -> 40 ms(100 dB HL)
    taus = 0.0004 * np.maximum(hl_sub, 0.0)
    frame_rate = sr / HOP
    for j, tau in enumerate(taus):
        if tau <= 0:
            continue
        a = float(np.exp(-1.0 / (tau * frame_rate)))
        # lfilter: y[n] = a*y[n-1] + (1-a)*x[n]
        gain_db[:, j] = signal.lfilter([1 - a], [1, -a], gain_db[:, j])

    # ---------- 4. 频谱涂抹：功率扩散（保持每帧总功率）
    widths = np.clip(0.15 + 0.004 * np.maximum(hl_sub, 0.0), 0.15, 0.55)
    spread = _gaussian_spreading_matrix(centers, widths)
    smeared_power = sub_power @ spread.T
    shape_ratio = np.sqrt(smeared_power / np.maximum(sub_power, 1e-20))
    gain_lin = 10 ** (gain_db / 20.0) * shape_ratio
    # 不可闻频带强制保持静音增益，阻止可闻频带的涂抹能量泄漏进来
    gain_lin = np.where(inaudible, 10 ** (INAUDIBLE_GAIN_DB / 20.0), gain_lin)
    bin_gain = gain_lin @ membership                    # (frames, bins)
    spec_out = spec * bin_gain

    # ---------- 5. 阈值底噪：模拟听损耳的神经自发放电（固定极低电平）
    # 生理学上内部噪声约 0 dB SPL，远低于任何可闻信号，只在不可闻频带注入，
    # 提供"安静环境下的轻微嘶声"质感，而不能盖过衰减后的真实信号。
    if add_threshold_noise:
        noise = rng.standard_normal(len(x))
        noise_spec, _, _ = stft(noise, sr)
        noise_power = np.maximum(np.abs(noise_spec) ** 2, 1e-20) * onesided
        n_sub_rms = (noise_power @ membership.T) * scale
        noise_floor_spl = 0.0                          # 固定 0 dB SPL
        target_rms = 10 ** (
            (noise_floor_spl - (DEFAULT_CAL_DB_SPL - 3.01)) / 10.0
        )
        n_gain = np.sqrt(target_rms / np.maximum(n_sub_rms, 1e-20))
        # 仅在该帧不可闻的频带注入；可闻频带完全不打扰
        mask = (~inaudible).astype(float)
        n_gain = n_gain * (1.0 - mask)
        n_bin_gain = n_gain @ membership
        spec_out = spec_out + noise_spec * n_bin_gain

    y = istft(spec_out, sr, length=len(x))
    peak = np.max(np.abs(y))
    if peak > 0.99:                                     # 防爆音
        y = y / peak * 0.99
    return y
