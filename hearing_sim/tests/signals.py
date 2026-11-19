"""测试用合成信号: 语音形噪声、类语音谐波串、扫频、啸叫音。"""
from __future__ import annotations

import numpy as np


def speech_shaped_noise(n: int, fs: int, rms: float = 0.1, rng: np.random.Generator | None = None) -> np.ndarray:
    """长时平均谱近似语音 (随频率 -9 dB/oct 衰减) 的成形噪声。"""
    rng = rng or np.random.default_rng(42)
    x = rng.standard_normal(n)
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    shape = 1.0 / np.sqrt(1.0 + (freqs / 500.0) ** 2)  # -6 dB/oct 量级
    spec *= shape
    y = np.fft.irfft(spec, n)
    y *= rms / (np.sqrt(np.mean(y**2)) + 1e-12)
    return y.astype(np.float32)


def harmonic_complex(n: int, fs: int, f0: float = 120.0, harmonics: int = 20,
                     rms: float = 0.1, rolloff: float = 1.0) -> np.ndarray:
    """带谐波滚降的谐波复合音 (类元音)。"""
    t = np.arange(n) / fs
    sig = np.zeros(n)
    for k in range(1, harmonics + 1):
        sig += np.sin(2 * np.pi * f0 * k * t) / (k**rolloff)
    sig *= rms / (np.sqrt(np.mean(sig**2)) + 1e-12)
    return sig.astype(np.float32)


def amplitude_modulated(n: int, fs: int, carrier_hz: float, mod_hz: float = 4.0,
                        depth: float = 0.8, rms: float = 0.1) -> np.ndarray:
    """调幅音 (模拟语音包络起伏, 测试压缩 attack/release)。"""
    t = np.arange(n) / fs
    env = 1.0 - depth + depth * (0.5 + 0.5 * np.sin(2 * np.pi * mod_hz * t))
    sig = env * np.sin(2 * np.pi * carrier_hz * t)
    sig *= rms / (np.sqrt(np.mean(sig**2)) + 1e-12)
    return sig.astype(np.float32)


def sine_tone(n: int, fs: int, freq_hz: float, rms: float = 0.1) -> np.ndarray:
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * freq_hz * t)
    return (sig * rms / np.sqrt(np.mean(sig**2))).astype(np.float32)


def inject_howl(x: np.ndarray, fs: int, howl_hz: float = 3200.0, gain: float = 0.25,
                start: float = 0.5, end: float | None = None) -> np.ndarray:
    """在信号中注入一段稳态窄带啸叫音。"""
    n = len(x)
    t = np.arange(n) / fs
    i0 = int(start * fs)
    i1 = int((end or (n / fs)) * fs)
    tone = np.zeros(n)
    tone[i0:i1] = gain * np.sin(2 * np.pi * howl_hz * t[i0:i1])
    return (x + tone).astype(np.float32)
