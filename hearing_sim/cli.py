"""命令行批处理: 对一个音频文件生成助听前/助听后两个版本并打印验配报告。

用法:
  py -3 cli.py --audio samples/demo_speech.wav \
      --audiogram samples/audiogram.csv --formula WDRC --fitting open \
      --out-dir out
听力图 CSV 两列: frequency_hz, loss_dbhl (含表头)。
"""
from __future__ import annotations

import argparse
import json
import os

from hearing_sim.audiogram import Audiogram, preset_presbycusis
from hearing_sim.engine import EngineConfig
from hearing_sim.pipeline import process_file


def main() -> None:
    ap = argparse.ArgumentParser(description="助听器验配模拟 CLI")
    ap.add_argument("--audio", required=True, help="输入音频 (wav/flac/ogg)")
    ap.add_argument("--audiogram", help="听力图 CSV; 不提供则用老年性聋示例")
    ap.add_argument("--formula", default="WDRC", choices=["NAL-R", "NAL-RP", "WDRC"])
    ap.add_argument("--fitting", default="open", choices=["open", "closed"])
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--no-feedback", action="store_true")
    ap.add_argument("--no-smearing", action="store_true")
    args = ap.parse_args()

    ag = Audiogram.from_csv(args.audiogram) if args.audiogram else preset_presbycusis()
    os.makedirs(args.out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.audio))[0]
    cfg = EngineConfig(
        formula=args.formula, fitting=args.fitting,
        enable_feedback=not args.no_feedback,
        enable_smearing=not args.no_smearing,
    )
    report = process_file(
        args.audio, ag,
        os.path.join(args.out_dir, f"{base}_unaided.wav"),
        os.path.join(args.out_dir, f"{base}_aided.wav"),
        cfg,
    )
    print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
    within_budget = report.realtime_factor < 2.0 / 60.0
    print(f"\n性能: {report.duration_s}s 音频用时 {report.elapsed_s}s "
          f"(RTF={report.realtime_factor}) -> {'达标' if within_budget else '超标'} (要求 RTF<0.0334)")


if __name__ == "__main__":
    main()
