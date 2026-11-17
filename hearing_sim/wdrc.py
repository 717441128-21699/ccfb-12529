"""宽动态范围压缩（WDRC）：轻声大声分开压缩。

处理在 STFT 域按通道完成：
1. 每个 STFT bin 按带边归入 8 个通道；
2. 每帧提取各通道输入电平（dB SPL，RMS 聚合）；
3. 通道增益 = WDRC 目标曲线在该电平上的插值，外加电平相关的平滑
   （攻击/释放时间常数），避免抽吸效应；
4. bin 级施加通道增益后返回。
"""
from __future__ import annotations

import numpy as np

from . import channels as ch_mod
from .prescriptions import LEVEL_LOUD, LEVEL_MEDIUM, LEVEL_SOFT, wdrc_targets


def level_attenuation(fs: int, tau_ms: float) -> float:
    """一阶 IIR 平滑系数 alpha = exp(-hop/(fs*tau))。"""
    dt = ch_mod_mod_hop(fs)
    return float(np.exp(-dt / (tau_ms * 1e-3)))


def ch_mod_mod_hop(fs: int) -> float:
    # 延迟 import 避免与 audio 模块形成循环依赖
    from .audio import HOP

    return HOP / fs


def channel_levels_db_spl(mag: np.ndarray, bin_channels: np.ndarray,
                          n_channels: int) -> np.ndarray:
    """STFT 域备用电平估计（按带内 bin 平均功率 + 纯音峰值分支）。

    主处理链使用时域带通 RMS（见 ``time_domain_channel_levels``），
    本函数保留给无原始波形的调用场景与单元测试。
    """
    n_frames = mag.shape[1]
    levels = np.full((n_channels, n_frames), -120.0)
    power = mag**2
    TONE_CAL_DB = 3.73
    for c in range(n_channels):
        sel = bin_channels == c
        if not np.any(sel):
            continue
        band = power[sel, :]
        k_bins = band.shape[0]
        mean_p = band.mean(axis=0)
        peak_p = band.max(axis=0)
        tone_like = peak_p > 0.6 * band.sum(axis=0)
        wide_cal = 10.0 * np.log10(max(k_bins, 1))
        level_mean = 10 * np.log10(np.maximum(mean_p, 1e-12)) + wide_cal
        level_peak = 10 * np.log10(np.maximum(peak_p, 1e-12)) + TONE_CAL_DB
        levels[c, :] = np.where(tone_like, level_peak, level_mean) + 100.0
    return levels


def time_domain_channel_levels(x: np.ndarray, fs: int, edges: np.ndarray,
                               frame_len: int, hop: int,
                               stft_Z: np.ndarray | None = None,
                               stft_freqs: np.ndarray | None = None) -> np.ndarray:
    """时域带通 RMS 电平估计（真实助听器架构），返回 [n_channels, n_frames] dB SPL。

    每通道用 4 阶 Butterworth 带通（sosfiltfilt 零相位）滤波后分帧算 RMS，
    不依赖 STFT bin 计数，宽带信号各通道标定天然一致。

    纯音/窄带信号只占通道带宽的一小部分，带通 RMS 会按带宽占比系统性偏低；
    因此并行做一个「峰值分支」：用 STFT 峰值 bin 功率（补 Hann 窗标定
    3.73 dB）估计窄带电平，当峰值占带内能量 60% 以上时启用，
    与商用助听器的 tone-detection 电路同理。
    """
    from scipy import signal

    n_channels = len(edges) - 1
    n_frames = 1 + (len(x) - frame_len) // hop
    levels = np.full((n_channels, n_frames), -120.0)
    nyq = fs / 2.0

    # 峰值分支：用峰值 bin 的稳态平均功率（跨帧平均，消除分帧窗效应），
    # 补已实测标定的 Hann 窗常数 3.73 dB；STFT 由引擎传入时直接复用
    if stft_Z is not None and stft_freqs is not None:
        Z = stft_Z
        f_stft = stft_freqs
    else:
        f_stft, _, Z = stft_light(x, fs, frame_len, hop)
    mag = np.abs(Z)
    power = mag**2
    bin_ch = assign_bins_light(f_stft, edges)
    TONE_CAL_DB = 3.73
    # 零拷贝滑动窗口视图（避免花式索引产生 n_frames×frame_len 的大临时数组）
    from numpy.lib.stride_tricks import sliding_window_view
    for c in range(n_channels):
        lo = max(edges[c] / nyq, 1e-4)
        hi = min(edges[c + 1] / nyq, 0.999)
        sos = signal.butter(2, [lo, hi], btype="bandpass", output="sos")
        # 单通因果滤波：电平检测只需稳态 RMS，群延迟不影响分通道增益精度，
        # 比 sosfiltfilt（正反两遍）省一半计算
        y = signal.sosfilt(sos, x)
        frames = sliding_window_view(y, frame_len)[::hop][:n_frames]
        band_power_frames = np.mean(frames**2, axis=1)
        wide_db = 10 * np.log10(np.maximum(band_power_frames, 1e-12)) + 100.0
        sel = bin_ch == c
        if np.any(sel):
            bp = power[sel, :]
            k = min(n_frames, bp.shape[1])
            # 峰值 bin 的跨帧平均功率（与 3.73 dB 标定常数的测量方式一致）
            peak_bin_idx = np.argmax(bp.mean(axis=1))
            peak_power = np.mean(bp[peak_bin_idx, :k])
            peak_level = 10 * np.log10(max(peak_power, 1e-18)) + TONE_CAL_DB + 100.0
            tone_ratio = bp.max(axis=0)[:k] / np.maximum(bp.sum(axis=0)[:k], 1e-18)
            tone_like = np.median(tone_ratio) > 0.6
            levels[c, :k] = np.full(k, peak_level) if tone_like else wide_db[:k]
        else:
            levels[c, :] = wide_db
    return levels


def _frame_band_power(y: np.ndarray, frame_len: int, hop: int,
                      n_frames: int) -> np.ndarray:
    frame_idx = np.arange(n_frames)[:, None] * hop + np.arange(frame_len)
    return np.mean(y[frame_idx] ** 2, axis=1)


def stft_light(x: np.ndarray, fs: int, frame_len: int, hop: int):
    """与 audio.stft 同参数的轻量封装，避免循环导入。"""
    from scipy import signal as sg
    return sg.stft(x, fs=fs, window="hann", nperseg=frame_len,
                   noverlap=frame_len - hop, boundary="zeros", padded=True)


def assign_bins_light(bin_freqs: np.ndarray, edges: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(edges, bin_freqs, side="right") - 1
    return np.clip(idx, 0, len(edges) - 2)


def gain_curve_at_level(target_soft: np.ndarray, target_medium: np.ndarray,
                        target_loud: np.ndarray, levels_spl: np.ndarray) -> np.ndarray:
    """把三锚点目标曲线插值到任意输入电平。

    targets 形状 [n_channels]，levels 形状 [n_channels, n_frames]，
    返回增益 [n_channels, n_frames]（dB）。
    """
    gains = np.empty_like(levels_spl)
    for c in range(levels_spl.shape[0]):
        xp = np.array([LEVEL_SOFT, LEVEL_MEDIUM, LEVEL_LOUD])
        fp = np.array([target_soft[c], target_medium[c], target_loud[c]])
        gains[c, :] = np.interp(levels_spl[c, :], xp, fp,
                                left=fp[0], right=fp[2])
    return gains


def smooth_gains(gains_db: np.ndarray, fs: int,
                 attack_ms: float = 5.0, release_ms: float = 80.0) -> np.ndarray:
    """增益平滑：增益下降走攻击时间，增益回升走释放时间。

    对 dB 域增益做方向相关的一阶平滑（前向逐帧，帧数通常几百，纯 Python 循环
    开销可接受；核心矩阵运算仍全部向量化）。
    """
    a_att = float(np.exp(-ch_mod_mod_hop(fs) / (attack_ms * 1e-3)))
    a_rel = float(np.exp(-ch_mod_mod_hop(fs) / (release_ms * 1e-3)))
    out = np.empty_like(gains_db)
    prev = gains_db[:, 0]
    out[:, 0] = prev
    for n in range(1, gains_db.shape[1]):
        target = gains_db[:, n]
        a = np.where(target < prev, a_att, a_rel)  # 增益变小→攻击
        prev = a * prev + (1.0 - a) * target
        out[:, n] = prev
    return out


def wdrc_gains(ag, fs: int, mag: np.ndarray, bin_freqs: np.ndarray,
               formula: str = "NAL-R", ear: str = "left",
               compression_ratios: np.ndarray | None = None,
               attack_ms: float = 5.0, release_ms: float = 80.0,
               extra_gain_db: np.ndarray | None = None,
               levels_spl: np.ndarray | None = None) -> np.ndarray:
    """计算每帧每通道增益（线性倍数），形状 [n_bins, n_frames]。

    extra_gain_db：每通道附加增益（dB），用于耳模泄漏补偿、啸叫削减等。
    levels_spl：预计算的时域带通电平 [n_channels, n_frames]；为 None 时
    退回 STFT 域估计器。
    """
    n_channels = ch_mod.NUM_CHANNELS
    bin_channels = ch_mod.assign_bins(bin_freqs)
    centers = ch_mod.band_centers()

    g_soft = wdrc_targets(ag, centers, LEVEL_SOFT, formula, ear, compression_ratios)
    g_med = wdrc_targets(ag, centers, LEVEL_MEDIUM, formula, ear, compression_ratios)
    g_loud = wdrc_targets(ag, centers, LEVEL_LOUD, formula, ear, compression_ratios)
    if extra_gain_db is not None:
        extra = np.asarray(extra_gain_db, dtype=float)
        g_soft = g_soft + extra
        g_med = g_med + extra
        g_loud = g_loud + extra

    if levels_spl is None:
        levels_spl = channel_levels_db_spl(mag, bin_channels, n_channels)
    # 帧数对齐（时域分帧数与 STFT 帧数可能差 1）
    nf = min(levels_spl.shape[1], mag.shape[1])
    levels_spl = levels_spl[:, :nf]
    gains_db = gain_curve_at_level(g_soft, g_med, g_loud, levels_spl)
    gains_db = smooth_gains(gains_db, fs, attack_ms, release_ms)

    # 通道增益展开到 bin
    bin_gain_db = gains_db[bin_channels, :]
    full = np.zeros((mag.shape[0], mag.shape[1]))
    full[:, :nf] = bin_gain_db
    full[:, nf:] = bin_gain_db[:, -1:]
    return 10.0 ** (full / 20.0), gains_db
