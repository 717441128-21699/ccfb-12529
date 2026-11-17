"""测试与演示用合成信号（不依赖外部音频文件即可跑通全流程）。"""
from __future__ import annotations

import numpy as np


def pure_tone(freq_hz: float, duration_s: float, fs: int,
              level_dbfs: float = -20.0) -> np.ndarray:
    """单频正弦，level_dbfs 按 RMS 标定（与系统电平估计器约定一致）。"""
    t = np.arange(int(duration_s * fs)) / fs
    rms = 10.0 ** (level_dbfs / 20.0)
    return rms * np.sqrt(2.0) * np.sin(2 * np.pi * freq_hz * t)


def multi_tone(freqs_hz, duration_s: float, fs: int,
               level_dbfs: float = -20.0) -> np.ndarray:
    """多频等响正弦叠加。"""
    t = np.arange(int(duration_s * fs)) / fs
    sig = np.zeros_like(t)
    for f in freqs_hz:
        sig += np.sin(2 * np.pi * f * t)
    sig /= max(len(freqs_hz), 1)
    return sig * 10.0 ** (level_dbfs / 20.0)


def speech_like_signal(duration_s: float, fs: int,
                       rng: np.random.Generator | None = None) -> np.ndarray:
    """类言语信号：慢速调幅的宽带噪声 + 谐波脉冲串，模拟言语的频谱与节奏。"""
    rng = rng or np.random.default_rng(0)
    n = int(duration_s * fs)
    t = np.arange(n) / fs

    # 基频 120 Hz 的谐波源（浊音）
    f0 = 120.0
    harmonic = np.zeros(n)
    for k in range(1, 12):
        harmonic += (1.0 / k) * np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28))
    harmonic /= np.max(np.abs(harmonic))

    # 宽带噪声（清音/擦音）
    noise = rng.standard_normal(n)
    # 简单低通，让能量集中在言语频段
    from scipy import signal
    b, a = signal.butter(4, 5000 / (fs / 2), btype="low")
    noise = signal.lfilter(b, a, noise)

    # 3–6 Hz 言语节奏调幅 + 随机停顿
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 4.0 * t)
    gate = (np.sin(2 * np.pi * 1.7 * t) > -0.2).astype(float)
    mix = 0.6 * harmonic + 0.4 * noise
    sig = mix * envelope * gate

    # 频谱倾斜：言语高频自然衰减
    sig = signal.lfilter([1.0], [1.0, -0.6], sig)
    return sig / np.max(np.abs(sig)) * 0.5


def band_limited_noise(lo_hz: float, hi_hz: float, duration_s: float, fs: int,
                       level_dbfs: float = -35.0,
                       rng: np.random.Generator | None = None) -> np.ndarray:
    """带限白噪声：能量均匀铺满指定频段，用于通道电平/增益的精确测量。

    纯音在 STFT 中只占少数 bin，用「通道平均功率」估计电平会系统性偏低；
    带限噪声让通道内所有 bin 都有能量，估计器输入与设计假设一致。
    """
    from scipy import signal

    rng = rng or np.random.default_rng(0)
    n = int(duration_s * fs)
    x = rng.standard_normal(n)
    sos = signal.butter(6, [lo_hz / (fs / 2), hi_hz / (fs / 2)],
                        btype="bandpass", output="sos")
    x = signal.sosfilt(sos, x)
    rms = np.sqrt(np.mean(x**2))
    target_rms = 10.0 ** (level_dbfs / 20.0)
    return x / rms * target_rms


def inject_howl(x: np.ndarray, fs: int, howl_freqs_hz=(2700.0, 4300.0),
                level_dbfs: float = -12.0, duration_s: float | None = None) -> np.ndarray:
    """在信号中注入持续窄带啸叫，用于验证检测/抑制链路。"""
    n = len(x) if duration_s is None else int(duration_s * fs)
    t = np.arange(n) / fs
    howl = np.zeros(n)
    for f in howl_freqs_hz:
        howl += np.sin(2 * np.pi * f * t)
    howl /= max(len(howl_freqs_hz), 1)
    howl *= 10.0 ** (level_dbfs / 20.0)
    out = x.copy()
    out[:n] += howl
    return out
