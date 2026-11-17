"""命令行演示：不启动网页也能跑通完整验配并生成试听 WAV。

用法（在 workspace 根目录）：
    py -I scripts/demo_cli.py
    py -I scripts/demo_cli.py --preset 中重度高频陡降 --mold open --howl
输出：
    outputs/demo_unaided.wav   裸耳听损模拟
    outputs/demo_aided.wav     助听后
    控制台打印完整验配报告与性能数据
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows GBK 控制台兜底：emoji 与特殊符号转 ASCII 安全输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import numpy as np  # noqa: E402

from hearing_sim import audio, engine, synth  # noqa: E402
from hearing_sim.audiogram import PRESETS, Audiogram  # noqa: E402
from hearing_sim.channels import band_centers  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="助听器验配命令行演示")
    ap.add_argument("--preset", default="轻度老年性聋(高频缓降)", choices=list(PRESETS))
    ap.add_argument("--formula", default="NAL-R", choices=["NAL-R", "NAL-RP", "POGO", "FIG6"])
    ap.add_argument("--mold", default="open", choices=["open", "closed"])
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--howl", action="store_true", help="注入啸叫演示自动抑制")
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()

    fs = 24000
    ag = Audiogram.from_preset(args.preset)
    rng = np.random.default_rng(args.seed)
    x = synth.speech_like_signal(args.seconds, fs, rng)
    if args.howl:
        x = synth.inject_howl(x, fs, howl_freqs_hz=(2700.0, 4300.0), level_dbfs=-10.0)

    res = engine.process(x, fs, ag, formula=args.formula,
                         mold_type=args.mold, detect_feedback=True)
    rep = res.report

    out_dir = ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    audio.save_wav(out_dir / "demo_unaided.wav", res.unaided, fs)
    audio.save_wav(out_dir / "demo_aided.wav", res.aided, fs)

    centers = band_centers()
    print("=" * 72)
    print(f"预设听力图: {args.preset} | 公式: {args.formula} | 耳模: {args.mold}")
    print("-" * 72)
    print(f"{'通道中心Hz':>12}" + "".join(f"{c:>9.0f}" for c in centers))
    print(f"{'处方目标dB':>12}" + "".join(f"{g:>9.1f}" for g in rep.target_gains_db))
    print(f"{'实际增益dB':>12}" + "".join(f"{g:>9.1f}" for g in np.asarray(rep.applied_gains_db)))
    print(f"{'泄漏补偿dB':>12}" + "".join(f"{g:>9.1f}" for g in rep.occlusion.compensation_db))
    print(f"{'稳定余量dB':>12}" + "".join(f"{g:>9.1f}" for g in rep.stability_margin_db))
    if rep.occlusion.capped_channels:
        print(f"⚠ 补偿触顶通道: {[c + 1 for c in rep.occlusion.capped_channels]}")
    if rep.feedback and rep.feedback.howls:
        print("🔊 啸叫频点:", [f"{h.freq_hz:.0f}Hz" for h in rep.feedback.howls])
        print("   陷波频率:", [f"{f:.0f}Hz" for f in rep.feedback.notch_freqs])
    print("-" * 72)
    print(f"音频时长 {rep.audio_duration_seconds:.1f}s | 处理耗时 {rep.processing_seconds:.3f}s "
          f"| 实时倍率 {rep.realtime_ratio:.1f}x | 达标(<2s): {rep.processing_seconds < 2.0}")
    print(f"输出文件: {out_dir / 'demo_unaided.wav'}")
    print(f"          {out_dir / 'demo_aided.wav'}")
    print("=" * 72)


if __name__ == "__main__":
    main()
