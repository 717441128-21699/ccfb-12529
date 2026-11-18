"""生成演示音频：言语谱形噪声 + 可选啸叫纯音，供试听与测试。

用法：
  py scripts/make_demo.py --speech out_speech.wav
  py scripts/make_demo.py --howl out_howl.wav --howl-freq 3150
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearing_aid_sim.audio_io import (pure_tone, save_audio,
                                      speech_shaped_noise)
from hearing_aid_sim.config import DEFAULT_SR


def main():
    ap = argparse.ArgumentParser(description="生成验配演示音频")
    ap.add_argument("out", help="输出 wav 路径")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--level", type=float, default=65.0, help="言语电平 dB SPL")
    ap.add_argument("--howl", action="store_true", help="叠加啸叫纯音")
    ap.add_argument("--howl-freq", type=float, default=3150.0)
    ap.add_argument("--howl-level", type=float, default=78.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    sr = DEFAULT_SR
    n = int(sr * args.seconds)
    rng = np.random.default_rng(args.seed)
    x = speech_shaped_noise(n, sr, args.level, rng)
    if args.howl:
        x = x + pure_tone(args.howl_freq, sr, args.howl_level, n=n)
        peak = np.max(np.abs(x))
        if peak > 0.99:
            x = x / peak * 0.95
    save_audio(args.out, x, sr)
    print(f"已生成 {args.out}（{args.seconds}s, {sr} Hz, 言语 {args.level} dB SPL"
          + (f"，啸叫 {args.howl_freq} Hz" if args.howl else "") + "）")


if __name__ == "__main__":
    main()
