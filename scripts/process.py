"""命令行验配处理：输入音频 + 听力图，输出裸耳/戴机两个试听版本。

听力图用 JSON 描述：
  {"freqs": [125,250,...], "hl": [25,25,...], "ear": "right"}

用法：
  py scripts/process.py input.wav audiogram.json --outdir out/ \
      --formula nal-r --coupling open
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearing_aid_sim.audio_io import load_audio, save_audio
from hearing_aid_sim.audiogram import Audiogram
from hearing_aid_sim.config import DEFAULT_SR
from hearing_aid_sim.engine import HearingAidEngine


def load_audiogram(path: str) -> Audiogram:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Audiogram(
        freqs=np.asarray(data["freqs"], dtype=float),
        hl=np.asarray(data["hl"], dtype=float),
        ear=data.get("ear", "right"),
    )


def main():
    ap = argparse.ArgumentParser(description="助听器验配模拟 CLI")
    ap.add_argument("audio", help="输入音频 wav/flac/ogg")
    ap.add_argument("audiogram", help="听力图 JSON")
    ap.add_argument("--outdir", default="output", help="输出目录")
    ap.add_argument("--formula", default="nal-r",
                    choices=["nal-r", "nal-rp", "pogo"])
    ap.add_argument("--coupling", default="open", choices=["open", "closed"])
    ap.add_argument("--sr", type=int, default=DEFAULT_SR)
    ap.add_argument("--no-feedback", action="store_true",
                    help="关闭啸叫检测与陷波")
    args = ap.parse_args()

    ag = load_audiogram(args.audiogram)
    x, sr = load_audio(args.audio, target_sr=args.sr)
    eng = HearingAidEngine(ag, sr=sr, formula=args.formula,
                           coupling=args.coupling,
                           enable_feedback=not args.no_feedback)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.audio).stem

    y_aided = eng.process_aided(x)
    y_unaided = eng.process_unaided(x)
    save_audio(outdir / f"{stem}_aided.wav", y_aided, sr)
    save_audio(outdir / f"{stem}_unaided.wav", y_unaided, sr)

    r = eng.report
    print(f"听力图: PTA={ag.pta():.0f} dB HL（{ag.degree()}），{ag.ear}耳")
    print(f"处方公式: {args.formula}，耳模: {args.coupling}")
    print("通道频率 Hz :", np.round(r.channel_freqs).astype(int).tolist())
    print("处方目标 dB:", np.round(r.prescription_db, 1).tolist())
    print("漏音补偿 dB:", np.round(r.vent_comp_db, 1).tolist())
    print("最终目标 dB:", np.round(r.target_db, 1).tolist())
    if r.howls:
        print("检出啸叫频点:",
              [f"{h.freq_hz:.0f} Hz" for h in r.howls])
    print(f"输出: {outdir / stem}_aided.wav / _unaided.wav")


if __name__ == "__main__":
    main()
