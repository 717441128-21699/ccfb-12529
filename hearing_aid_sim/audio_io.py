"""音频读写与测试信号生成。

音频文件支持 wav / flac / ogg（soundfile 后端），
读入时统一为单声道 float64、按目标采样率重采样。
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from .config import DEFAULT_CAL_DB_SPL


def load_audio(path: str, target_sr: int | None = None) -> tuple[np.ndarray, int]:
    import soundfile as sf
    x, sr = sf.read(path, dtype="float64", always_2d=False)
    if x.ndim > 1:                       # 多声道取平均（单耳验配）
        x = x.mean(axis=1)
    if target_sr is not None and sr != target_sr:
        n = int(round(len(x) * target_sr / sr))
        x = signal.resample_poly(x, target_sr, sr)[:n]
        sr = target_sr
    return x, sr


def save_audio(path, x: np.ndarray, sr: int) -> None:
    """保存音频。path 可为文件路径或文件对象（后者按 WAV 写出）。"""
    import soundfile as sf
    x = np.asarray(x, dtype=float)
    peak = np.max(np.abs(x)) if x.size else 0.0
    if peak > 0.999:
        x = x / peak * 0.999
    if hasattr(path, "write"):                  # 文件对象（如 BytesIO）
        sf.write(path, x.astype(np.float32), sr, format="WAV")
    else:
        sf.write(path, x.astype(np.float32), sr)


def spl_to_amp(level_db_spl: float, cal_db_spl: float = DEFAULT_CAL_DB_SPL) -> float:
    """目标 dB SPL（正弦 RMS 电平）对应的线性峰值幅度。

    校准约定：0 dBFS 正弦峰值 = cal_db_spl dB SPL。
    正弦 RMS = 峰值/√2，故峰值 = 10^((SPL-cal)/20)。
    """
    return 10 ** ((level_db_spl - cal_db_spl) / 20.0)


def speech_shaped_noise(n: int, sr: int, level_db_spl: float = 65.0,
                        rng: np.random.Generator | None = None) -> np.ndarray:
    """生成指定 RMS 电平（dB SPL）的言语谱形噪声。

    长期平均言语谱用 800 Hz 拐点的一阶低通近似（-6 dB/oct 滚降）。
    """
    rng = rng or np.random.default_rng(1)
    white = rng.standard_normal(n)
    b, a = signal.butter(1, 800.0 / (sr / 2), btype="low")
    shaped = signal.lfilter(b, a, white)
    shaped /= np.sqrt(np.mean(shaped ** 2))          # 归一 RMS=1（0 dBFS RMS）
    rms_dbfs = level_db_spl - (DEFAULT_CAL_DB_SPL - 3.01)
    return shaped * 10 ** (rms_dbfs / 20.0)


def pure_tone(freq_hz: float, sr: int, level_db_spl: float = 65.0,
              n: int | None = None, duration: float = 1.0) -> np.ndarray:
    """指定 RMS 电平（dB SPL）的正弦波。

    长度由 n（样点数）或 duration（秒，默认 1 秒）给定。
    spl_to_amp 返回的即正弦峰值幅度。
    """
    if n is None:
        n = int(round(sr * duration))
    t = np.arange(n) / sr
    return spl_to_amp(level_db_spl) * np.sin(2 * np.pi * freq_hz * t)


def multi_tone(freqs, n: int, sr: int, level_db_spl: float = 65.0,
               rng: np.random.Generator | None = None) -> np.ndarray:
    """等幅多频复合音，整体 RMS 对应指定 dB SPL（每分量低 10log10(k) dB）。"""
    rng = rng or np.random.default_rng(2)
    t = np.arange(n) / sr
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    sig = np.zeros(n)
    for f, ph in zip(freqs, phases):
        sig += np.sin(2 * np.pi * f * t + ph)
    sig /= np.sqrt(np.mean(sig ** 2))                  # 归一 RMS=1
    rms_dbfs = level_db_spl - (DEFAULT_CAL_DB_SPL - 3.01)
    return sig * 10 ** (rms_dbfs / 20.0)


def band_limited_noise(band_edges, n: int, sr: int,
                       level_db_spl: float = 65.0,
                       rng: np.random.Generator | None = None) -> np.ndarray:
    """ANSI S3.22 式分带噪声：每条频带独立带通噪声、等电平叠加。

    能量在各带内均匀分布，不存在复合音的跨带窗泄漏问题，
    是处方公式目标符合度验证的标准激励信号。
    各带使用独立随机相位并做软峰值控制，整体峰因子约 6 dB，
    避免多带叠加的瞬时峰值触发削波。
    """
    rng = rng or np.random.default_rng(9)
    edges = np.asarray(band_edges, dtype=float)
    total = np.zeros(n)
    n_bands = len(edges) - 1
    for i in range(n_bands):
        lo = max(edges[i] / (sr / 2), 1e-4)
        hi = min(edges[i + 1] / (sr / 2), 0.999)
        sos = signal.butter(4, [lo, hi], btype="band", output="sos")
        band = signal.sosfilt(sos, rng.standard_normal(n))
        band /= np.sqrt(np.mean(band ** 2))            # 每带 RMS=1
        total += band / np.sqrt(n_bands)
    # 软峰值控制：把峰因子压到 ~6 dB 且不改变长期 RMS
    peak = np.max(np.abs(total))
    target_peak = 2.0
    if peak > target_peak:
        total = np.tanh(total / peak * target_peak) / np.tanh(target_peak) * peak
    total /= np.sqrt(np.mean(total ** 2))
    rms_dbfs = level_db_spl - (DEFAULT_CAL_DB_SPL - 3.01)
    return total * 10 ** (rms_dbfs / 20.0)
