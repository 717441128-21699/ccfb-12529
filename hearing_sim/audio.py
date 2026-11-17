"""音频 I/O 与 STFT 工具。

约定：
- 内部全部使用 float64、单声道；
- 0 dBFS 校准为 100 dB SPL（CAL_DB_SPL），即 dB SPL = dBFS + 100；
- STFT 用 1024 点 Hann 窗、75% 重叠（hop=256），scipy 的 istft 在该参数下
  可对分析信号做近乎完美的重建。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

# 0 dBFS 对应的声压级。真实设备应通过声级计校准，此处取行业模拟常用值。
CAL_DB_SPL = 100.0
NPPERSEG = 1024
HOP = 256
WINDOW = "hann"


def to_mono(x: np.ndarray) -> np.ndarray:
    """任意形状音频转单声道 float64。"""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    return x.ravel()


def load_mono(path) -> tuple[np.ndarray, int]:
    """读取音频文件并转单声道 float64，返回 (波形, 采样率)。

    path 可以是路径字符串/Path，也可以是 soundfile 支持的文件对象
    （Flask 上传的 SpooledTemporaryFile 直接传入即可）。
    """
    target = str(path) if isinstance(path, (str, Path)) else path
    x, fs = sf.read(target, always_2d=False)
    return to_mono(x), int(fs)


def save_wav(path, x: np.ndarray, fs: int) -> None:
    """保存为 16-bit PCM WAV，写入前做 -1 dBFS 软保护。

    path 为文件对象（如 BytesIO）时显式指定 format，soundfile 无法
    从无扩展名的流推断容器格式。
    """
    x = to_mono(x)
    peak = np.max(np.abs(x)) if x.size else 0.0
    if peak > 10 ** (-1.0 / 20):
        x = x / peak * 10 ** (-1.0 / 20)
    kwargs = {"subtype": "PCM_16"}
    if not isinstance(path, (str, Path)):
        kwargs["format"] = "WAV"
    sf.write(str(path) if isinstance(path, (str, Path)) else path,
             x.astype(np.float64), fs, **kwargs)


def stft(x: np.ndarray, fs: int):
    """返回 (频率轴, 时间轴, 复频谱 Z[bin, frame])。"""
    f, t, Z = signal.stft(
        x,
        fs=fs,
        window=WINDOW,
        nperseg=NPPERSEG,
        noverlap=NPPERSEG - HOP,
        boundary="zeros",
        padded=True,
    )
    return f, t, Z


def istft(Z: np.ndarray, fs: int, length: int | None = None) -> np.ndarray:
    """STFT 逆变换，可裁剪回原始长度。"""
    _, x = signal.istft(
        Z,
        fs=fs,
        window=WINDOW,
        nperseg=NPPERSEG,
        noverlap=NPPERSEG - HOP,
        boundary=True,
    )
    if length is not None:
        x = x[:length]
    return x


def rms_dbfs(x: np.ndarray) -> float:
    """整段 RMS 电平（dBFS）。"""
    x = to_mono(x)
    if x.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(x**2)))
    return 20.0 * np.log10(max(rms, 1e-12))


def dbfs_to_spl(dbfs: np.ndarray | float) -> np.ndarray | float:
    return np.asarray(dbfs) + CAL_DB_SPL


def spl_to_dbfs(spl: np.ndarray | float) -> np.ndarray | float:
    return np.asarray(spl) - CAL_DB_SPL


def peak_soft_limit(x: np.ndarray, ceiling_dbfs: float = -1.0) -> np.ndarray:
    """tanh 软限幅，把峰值限制在 ceiling_dbfs 以下。"""
    ceiling = 10.0 ** (ceiling_dbfs / 20.0)
    return ceiling * np.tanh(x / ceiling)
