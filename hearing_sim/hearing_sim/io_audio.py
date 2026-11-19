"""音频读写与重采样。

统一内部工作采样率 32 kHz、单声道、float32、峰值 <= 1。
支持 wav/flac/ogg (libsndfile); 不依赖 ffmpeg, 不支持压缩 mp3 输入。
"""
from __future__ import annotations

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from . import ENGINE_FS


def load_audio(path: str, target_fs: int = ENGINE_FS) -> tuple[np.ndarray, int]:
    """读取音频并转单声道、重采样到 target_fs。"""
    data, fs = sf.read(path, dtype="float32", always_2d=True)
    x = data.mean(axis=1)  # 多声道混缩为单声道
    if fs != target_fs:
        from math import gcd

        g = gcd(int(fs), int(target_fs))
        x = resample_poly(x, target_fs // g, fs // g)
    peak = np.max(np.abs(x)) if x.size else 0.0
    if peak > 1.0:
        x = x / peak
    return x.astype(np.float32), target_fs


def save_audio(path: str, x: np.ndarray, fs: int = ENGINE_FS) -> None:
    x = np.asarray(x, np.float32)
    peak = np.max(np.abs(x)) if x.size else 0.0
    if peak > 0.99:
        x = x * (0.99 / peak)
    sf.write(path, x, fs, subtype="PCM_16")


def duration_s(x: np.ndarray, fs: int) -> float:
    return len(x) / fs
