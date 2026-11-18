"""STFT/ISTFT 与频带聚合工具。

采用 75% 重叠 Hann 窗、COLA 归一化的分析-合成框架，
所有处理在 (n_frames, n_bins) 的复数谱上矢量化完成，
这是 1 分钟录音 < 2 秒处理指标的关键。
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from .config import BAND_EDGES, HOP, N_FFT, WINDOW


def stft(x: np.ndarray, sr: int, n_fft: int = N_FFT, hop: int = HOP):
    """返回 (frames, bins) 复数谱、bin 频率、窗函数。"""
    win = signal.get_window(WINDOW, n_fft)
    f, t, spec = signal.stft(
        x, fs=sr, window=win, nperseg=n_fft, noverlap=n_fft - hop,
        boundary="zeros", padded=True,
    )
    return spec.T, f, win          # scipy 输出 (bins, frames)，转置


def istft(spec_frames: np.ndarray, sr: int, n_fft: int = N_FFT,
          hop: int = HOP, length: int | None = None) -> np.ndarray:
    """逆变换，spec_frames 形状 (frames, bins)。"""
    win = signal.get_window(WINDOW, n_fft)
    _, x = signal.istft(
        spec_frames.T, fs=sr, window=win, nperseg=n_fft,
        noverlap=n_fft - hop, input_onesided=True,
    )
    if length is not None:
        x = x[:length]
    return x


def band_membership(bin_freqs: np.ndarray,
                    edges: np.ndarray = BAND_EDGES) -> np.ndarray:
    """bin -> 通道编号矩阵，返回 (n_channels, n_bins) 的 0/1 归属阵。

    边界 bin 归几何上更靠近中心频率的一侧。
    """
    idx = np.digitize(bin_freqs, edges) - 1
    idx = np.clip(idx, 0, len(edges) - 2)
    n_ch = len(edges) - 1
    m = np.zeros((n_ch, len(bin_freqs)))
    m[idx, np.arange(len(bin_freqs))] = 1.0
    # DC/Nyquist 之外没有能量的空通道保护（测试用合成信号时）
    return m


def subband_membership(bin_freqs: np.ndarray, n_sub: int = 32,
                       f_lo: float = 100.0, f_hi: float | None = None):
    """对数等距子带划分（用于频谱涂抹），返回 (归属阵, 子带中心频率, 边)。

    f_hi 默认取 bin 网格的 Nyquist，避免高频 bin 被 digitize 钳到
    最后一个子带而错误聚集能量。
    """
    if f_hi is None:
        f_hi = float(bin_freqs[-1])
    edges = np.logspace(np.log10(f_lo), np.log10(f_hi), n_sub + 1)
    m = band_membership(bin_freqs, edges)
    centers = np.sqrt(edges[:-1] * edges[1:])
    return m, centers, edges


def rms_to_spl(level_fs_rms_db: np.ndarray, cal_db_spl: float) -> np.ndarray:
    """FS 域 RMS 电平(dBFS) -> dB SPL。

    约定：0 dBFS 满量程正弦峰值 = cal_db_spl dB SPL，
    故 RMS=1（0 dBFS RMS）对应 cal_db_spl - 3.01 dB SPL。
    """
    return np.asarray(level_fs_rms_db) + cal_db_spl - 3.01


def band_levels_db_spl(spec_frames: np.ndarray, membership: np.ndarray,
                       cal_db_spl: float, n_fft: int = N_FFT,
                       window: str = WINDOW) -> np.ndarray:
    """每帧每通道的信号 RMS 电平（dB SPL），全矢量化。

    scipy STFT 采用 1/(N/2) 的 DFT 归一化。对加窗帧，单边谱频带 k 的
    信号 RMS 功率为：
        P_k = onesided_k * sum_{bins in band} |X|^2 * 2 / sum(w^2)
    其中 onesided=2（DC/Nyquist 为 1），sum(w^2) 为窗能量
    （Hann、N=1024 时为 384）。系数 2/sum(w^2) 已由白噪声数值标定。

    Parameters
    ----------
    spec_frames : (n_frames, n_bins) 复数谱
    membership  : (n_channels, n_bins) 0/1 归属阵
    """
    win = signal.get_window(window, n_fft)
    scale = 2.0 / np.sum(win ** 2)
    n_bins = spec_frames.shape[1]
    onesided = np.full(n_bins, 2.0)
    onesided[0] = 1.0
    if n_bins > 1:
        onesided[-1] = 1.0
    power = np.maximum(np.abs(spec_frames) ** 2, 1e-20) * onesided
    band_power = power @ membership.T                    # (frames, ch)
    rms_power = band_power * scale
    return rms_to_spl(10 * np.log10(rms_power + 1e-20), cal_db_spl)
