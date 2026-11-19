"""生成演示用音频样本 (全部合成, 无外部数据依赖)。

生成内容:
- demo_speech.wav: 类语音信号 (基频颤动 + 谐波 + 共振峰 + 包络 + 轻噪声), 20 秒;
- calibration_1k.wav: 1 kHz 校准音。
"""
from __future__ import annotations

import numpy as np

from hearing_sim import ENGINE_FS
from hearing_sim.calibration import calibration_tone
from hearing_sim.io_audio import save_audio


def _formant(t: np.ndarray, center: float, bw: float, fs: int, rng) -> np.ndarray:
    """用带通白噪声塑造一个共振峰能量团。"""
    from scipy.signal import butter, sosfilt

    noise = rng.standard_normal(len(t))
    low = max(center - bw, 20.0) / (fs / 2)
    high = min(center + bw, fs / 2 - 1) / (fs / 2)
    sos = butter(4, [low, high], btype="band", output="sos")
    return sosfilt(sos, noise)

def make_speech_like(duration_s: float = 20.0, fs: int = ENGINE_FS,
                     seed: int = 123) -> np.ndarray:
    """合成类语音: 元音段(谐波+共振峰)与辅音段(宽带噪声)交替, 带自然停顿。"""
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    t = np.arange(n) / fs
    out = np.zeros(n)

    # 音节节奏: 每 0.6~1.1 秒一个音节, 元音/辅音交替
    pos = 0
    vowel = True
    while pos < n:
        syl_len = int(fs * rng.uniform(0.45, 0.95))
        gap = int(fs * rng.uniform(0.05, 0.2))
        end = min(pos + syl_len, n)
        seg_t = np.arange(end - pos) / fs

        if vowel:
            # 基频 110~140 Hz 缓慢颤动
            f0 = rng.uniform(110, 140)
            vibrato = 1.0 + 0.02 * np.sin(2 * np.pi * 5 * seg_t)
            phase = 2 * np.pi * f0 * np.cumsum(vibrato) / fs
            harmonic = np.zeros(end - pos)
            for k in range(1, 18):
                harmonic += np.sin(k * phase) / k
            # 两个共振峰 (随音节变化)
            f1 = rng.uniform(700, 1000)
            f2 = rng.uniform(1800, 2800)
            form = (_formant(seg_t, f1, 120, fs, rng)
                    + 0.7 * _formant(seg_t, f2, 200, fs, rng))
            seg = 0.5 * harmonic + 1.2 * form
        else:
            # 辅音: 高通宽带噪声 (摩擦音 /s/ /sh/)
            from scipy.signal import butter, sosfilt
            cf = rng.uniform(3500, 6000)
            sos = butter(4, cf / (fs / 2), btype="high", output="sos")
            seg = sosfilt(sos, rng.standard_normal(end - pos))

        # 音节包络 (起音/收音), 避免咔哒声
        ramp = int(0.03 * fs)
        env = np.ones(end - pos)
        env[:ramp] = np.linspace(0, 1, min(ramp, end - pos))
        env[-ramp:] = np.linspace(1, 0, min(ramp, end - pos))
        out[pos:end] += seg * env * 0.3

        pos = end + gap
        vowel = not vowel

    # 整体 RMS 归一到 0.05 (-26 dBFS 工作点)
    out *= 0.05 / max(np.sqrt(np.mean(out**2)), 1e-9)
    return out.astype(np.float32)


def main(out_dir: str = "samples") -> None:
    import os

    os.makedirs(out_dir, exist_ok=True)
    speech = make_speech_like()
    save_audio(os.path.join(out_dir, "demo_speech.wav"), speech, ENGINE_FS)
    tone = calibration_tone(ENGINE_FS)
    save_audio(os.path.join(out_dir, "calibration_1k.wav"), tone, ENGINE_FS)
    print(f"已生成 {out_dir}/demo_speech.wav ({len(speech)/ENGINE_FS:.1f}s)")
    print(f"已生成 {out_dir}/calibration_1k.wav (1 kHz 校准音)")


if __name__ == "__main__":
    main()
