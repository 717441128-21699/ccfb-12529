"""性能基准：一分钟录音的两个版本处理耗时（验收指标 4，阈值 2 秒）。"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearing_aid_sim.audiogram import Audiogram
from hearing_aid_sim.audio_io import speech_shaped_noise
from hearing_aid_sim.engine import HearingAidEngine


def main():
    sr = 44100
    ag = Audiogram.standard(
        np.array([25, 25, 30, 35, 45, 55, 60, 65, 70], dtype=float))
    rng = np.random.default_rng(21)
    x = speech_shaped_noise(60 * sr, sr, 65.0, rng)

    eng = HearingAidEngine(ag, sr=sr, coupling="open")

    t0 = time.perf_counter()
    eng.process_aided(x)
    aided_t = time.perf_counter() - t0

    t0 = time.perf_counter()
    eng.process_unaided(x)
    unaided_t = time.perf_counter() - t0

    print(f"录音长度: 60.0 s ({len(x)} 样点 @ {sr} Hz)")
    print(f"戴机处理: {aided_t:.2f} s  (实时倍率 {60 / aided_t:.0f}x)")
    print(f"裸耳模拟: {unaided_t:.2f} s  (实时倍率 {60 / unaided_t:.0f}x)")
    assert aided_t < 2.0 and unaided_t < 2.0, "超过 2 秒验收阈值"
    print("PASS: 两个版本均在 2 秒内完成")


if __name__ == "__main__":
    main()
