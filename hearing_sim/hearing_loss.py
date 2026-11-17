"""裸耳听损模拟（验收指标 3）：让家属听到「老人现在听到的世界」。

只做电平衰减无法体现感音神经性聋的言语清晰度下降。本模块在 STFT 幅度谱上
依次施加三类机制（相位保留）：

1. 阈值门限（inaudibility）
   各频带成分低于该频率听阈即不可闻，直接置零——轻声辅音彻底消失；
2. 响度重振（recruitment）
   听损者动态范围变窄：听阈以上的声音响度增长异常陡峭。用分段线性的
   「受损响度映射」把正常 SPL 映射为受损者感知 SPL，听阈处静默、
   高电平时趋近正常；
3. 频谱涂抹（spectral smearing）
   外毛细细胞损伤使听觉滤波器展宽（ERB 增大），频率选择性下降，相邻频带
   能量互相掩蔽，辅音与共振峰边界模糊。实现为 ERB 域高斯展宽。
"""
from __future__ import annotations

import numpy as np

from .audio import CAL_DB_SPL

# 正常耳 ERB 常数（Glasberg & Moore 1990）
EAR_Q = 9.26449
MIN_BW = 24.7


def erb_hz(f_hz: np.ndarray) -> np.ndarray:
    """正常耳等效矩形带宽（Hz）。"""
    f = np.asarray(f_hz, dtype=float)
    return MIN_BW * (1.0 + f / (EAR_Q * MIN_BW))


def hz_to_erb(f_hz: np.ndarray) -> np.ndarray:
    f = np.asarray(f_hz, dtype=float)
    return EAR_Q * np.log(1.0 + f / (EAR_Q * MIN_BW))


def erb_to_hz(erb: np.ndarray) -> np.ndarray:
    return EAR_Q * MIN_BW * (np.exp(np.asarray(erb, dtype=float) / EAR_Q) - 1.0)


def recruitment_gain_db(input_spl: np.ndarray, hl_db: np.ndarray,
                        power: float = 0.6) -> np.ndarray:
    """重振映射：返回受损耳相对正常耳的增益（dB，通常为负）。

    感音神经性聋的响度增长曲线在听阈附近极陡（recruitment）：
    小声几乎听不到，越过听阈后响度快速追赶，到 100 dB SPL 与正常耳等响。
    用幂律曲线连接 (HL, 增益=-HL) 与 (100, 增益=0)：

        G(SPL) = -HL * ((100-SPL)/(100-HL))^power,  HL < SPL < 100
        G(SPL) = 0,                                  SPL >= 100

    power<1 使曲线在听阈附近斜率远大于 1（异常陡峭的响度增长），
    高电平处斜率趋近 1（与正常耳等响）。

    输入可广播：input_spl [n_bins, n_frames]，hl_db [n_bins]。
    """
    hl = np.asarray(hl_db, dtype=float)[:, None]
    spl = np.asarray(input_spl, dtype=float)
    upper = 100.0
    frac = np.clip((upper - spl) / np.maximum(upper - hl, 1.0), 0.0, 1.0)
    gain = -hl * frac**power
    return np.where(spl >= upper, 0.0, gain)


def spectral_smear(mag: np.ndarray, bin_freqs: np.ndarray,
                   hl_db: np.ndarray, n_erb_grid: int = 96,
                   frame_step: int = 3) -> np.ndarray:
    """ERB 域高斯展宽，展宽量随听阈增大。

    mag [n_bins, n_frames]，hl_db [n_bins]（dB HL）。
    展宽系数 sigma_ERB = 0.5 + HL/40。

    性能设计：
    - bin↔ERB 网格的插值权重预算成映射矩阵，全部帧矩阵乘法完成；
    - 高斯权重只保留 ±3σ 内的非零项（稀疏化）；
    - 耳蜗频率选择性是慢变过程，长信号每隔 frame_step 帧算一次涂抹、
      中间帧复用，计算量减半而听感无差别。
    """
    n_bins, n_frames = mag.shape
    erb = hz_to_erb(bin_freqs)
    grid = np.linspace(erb[0], erb[-1], n_erb_grid)

    # bin → ERB 网格的线性插值权重矩阵 W1 [n_grid, n_bins]
    W1 = np.zeros((n_erb_grid, n_bins))
    idx = np.clip(np.searchsorted(grid, erb) - 1, 0, n_erb_grid - 2)
    g0, g1 = grid[idx], grid[idx + 1]
    w1 = np.clip((g1 - erb) / np.maximum(g1 - g0, 1e-12), 0.0, 1.0)
    W1[idx, np.arange(n_bins)] = w1
    W1[idx + 1, np.arange(n_bins)] = 1.0 - w1

    hl_grid = W1 @ np.asarray(hl_db, dtype=float)
    sigma_erb = 0.5 + hl_grid / 40.0

    # 高斯权重（±3σ 外已自然趋近 0，不做硬清零以免整行失效产生空 bin）
    diff = grid[:, None] - grid[None, :]
    weights = np.exp(-0.5 * (diff / sigma_erb[None, :]) ** 2)
    weights /= np.maximum(weights.sum(axis=1, keepdims=True), 1e-12)

    # 隔帧处理 + 前向填充：短信号（≤200 帧）全帧计算保证精度，
    # 长信号隔 frame_step 帧计算，耳蜗滤波慢变，听感无差别。
    # 网格→bin 用 np.interp 在 ERB 轴直接插值（128 网格 → 全部 STFT bin），
    # 不构造稀疏映射矩阵，避免网格点覆盖不到高频密集 bin。
    out = np.empty_like(mag)
    step = frame_step if n_frames > 200 else 1
    last_vals = None
    for n in range(n_frames):
        if n % step == 0:
            mag_grid = weights @ (W1 @ mag[:, n])
            last_vals = np.interp(erb, grid, mag_grid)
        out[:, n] = last_vals
    return out


def simulate_unaided(Z: np.ndarray, bin_freqs: np.ndarray, hl_db: np.ndarray,
                     smearing: bool = True,
                     levels_spl: np.ndarray | None = None) -> np.ndarray:
    """生成裸耳听损复频谱。

    Z       : 原始 STFT 复频谱 [n_bins, n_frames]
    hl_db   : 每个 bin 频率上的听阈（dB HL），由听力图插值得到
    返回处理后的复频谱（相位不变）。

    处理顺序：
    1. 分临界频带（复用助听器 8 通道划分）估计每帧带通电平与带听阈，
       在带内统一施加阈值门限与重振增益——耳蜗的响度编码本就按临界带
       整体发生，这样也避免逐 bin 处理时 STFT 泄漏把正弦能量误判为弱音；
    2. ERB 域频谱涂抹，模拟频率选择性下降（bin 级）。
    """
    from . import channels as ch_mod

    mag = np.abs(Z)
    n_bins, n_frames = mag.shape

    bin_channels = ch_mod.assign_bins(bin_freqs)
    centers = ch_mod.band_centers()
    hl_centers = np.interp(
        np.log2(np.maximum(centers, 1.0)),
        np.log2(np.maximum(bin_freqs, 1.0)),
        np.asarray(hl_db, dtype=float),
    )

    # 电平估计：优先使用引擎统一计算的时域带通 RMS，保证与助听链一致；
    # 独立调用时退回 STFT 域估计器。
    if levels_spl is not None:
        band_levels = levels_spl
    else:
        from .wdrc import channel_levels_db_spl
        band_levels = channel_levels_db_spl(mag, bin_channels, ch_mod.NUM_CHANNELS)
    nf = min(band_levels.shape[1], n_frames)
    band_levels = band_levels[:, :nf]

    # 带级增益（dB）：门限 + 重振。
    # 时域带通 RMS 是真实的带内平均声级，与听阈（dB HL 的 SPL 基准）直接
    # 可比，门限不再需要额外余量；退回 STFT 估计器时保留 6 dB 泄漏余量。
    gate_margin = 0.0 if levels_spl is not None else 6.0
    gain_band = recruitment_gain_db(band_levels, hl_centers)        # [C, T]
    audible = band_levels > (hl_centers[:, None] - gate_margin)
    gain_band = np.where(audible, gain_band, -120.0)

    # 展开到 bin 并施加（帧数不足时用最后一帧补齐到 STFT 帧数）
    bin_gain_db = gain_band[bin_channels, :]                         # [B, nf]
    if nf < n_frames:
        pad = np.repeat(bin_gain_db[:, -1:], n_frames - nf, axis=1)
        bin_gain_db = np.concatenate([bin_gain_db, pad], axis=1)
    # 线性增益：门限以下直接为 0（避免 10^-6 极小值参与后续运算）
    lin_gain = np.zeros_like(bin_gain_db)
    np.power(10.0, bin_gain_db / 20.0, out=lin_gain,
             where=bin_gain_db > -119.0)
    mag_loss = mag * lin_gain

    # 3) 频谱涂抹（在最终幅度上做，体现频率选择性丧失）
    if smearing:
        mag_loss = spectral_smear(mag_loss, bin_freqs, hl_db)

    # 保留原相位但避免 angle/exp 三角运算：用实增益直接缩放复频谱
    return Z * (mag_loss / np.maximum(mag, 1e-12))
