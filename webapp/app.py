"""Flask 后端：听力图录入、验配计算、音频处理与试听。

接口
----
GET  /                 单页应用
GET  /api/presets      听力图预设列表
POST /api/fit          提交听力图+验配选项，返回通道目标/泄漏/稳定余量等报告
POST /api/process      上传录音，返回裸耳/助听两个 WAV 与完整报告
GET  /api/demo-signal  生成内置类言语演示信号（无需用户准备音频）
"""
from __future__ import annotations

import io
import sys
import uuid
from pathlib import Path

# 允许从 webapp 子目录直接运行：把 workspace 根目录加入模块搜索路径
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from flask import Flask, jsonify, request, send_file, send_from_directory

from hearing_sim import audio, engine, synth
from hearing_sim.audiogram import PRESETS, STD_FREQS, Audiogram
from hearing_sim.channels import band_centers

app = Flask(__name__, static_folder="static", template_folder="templates")


def _parse_audiogram(payload: dict) -> Audiogram:
    freqs = np.asarray(payload["freqs"], dtype=float)
    left = np.asarray(payload["left_hl"], dtype=float)
    right = np.asarray(payload["right_hl"], dtype=float)
    return Audiogram(freqs, left, right)


def _report_to_dict(rep) -> dict:
    fb = rep.feedback
    return {
        "formula": rep.formula,
        "mold_type": rep.mold_type,
        "channel_centers_hz": rep.channel_centers_hz.tolist(),
        "target_gains_db": rep.target_gains_db.tolist(),
        "applied_gains_db": np.asarray(rep.applied_gains_db).tolist(),
        "leakage_db": rep.occlusion.leakage_db.tolist(),
        "compensation_db": rep.occlusion.compensation_db.tolist(),
        "capped_channels": rep.occlusion.capped_channels,
        "vent_fc_hz": rep.occlusion.fc_hz,
        "stability_margin_db": rep.stability_margin_db.tolist(),
        "stability_cuts_db": rep.stability_cuts_db.tolist(),
        "howls": [
            {"freq_hz": h.freq_hz, "persistence": h.persistence,
             "peak_db": h.peak_db, "channel": h.channel}
            for h in (fb.howls if fb else [])
        ],
        "notch_freqs": fb.notch_freqs if fb else [],
        "processing_seconds": rep.processing_seconds,
        "audio_duration_seconds": rep.audio_duration_seconds,
        "realtime_ratio": rep.realtime_ratio,
    }


@app.get("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.get("/api/presets")
def presets():
    return jsonify({
        "freqs": STD_FREQS.tolist(),
        "presets": {name: hl.tolist() for name, hl in PRESETS.items()},
    })


@app.post("/api/fit")
def fit():
    """只计算验配方案（不处理音频），用于前端实时绘图。"""
    p = request.get_json(force=True)
    ag = _parse_audiogram(p)
    # 用短类言语信号驱动一次完整处理以获得稳定的报告结构
    fs = 24000
    rng = np.random.default_rng(0)
    x = synth.speech_like_signal(2.0, fs, rng)
    res = engine.process(
        x, fs, ag,
        formula=p.get("formula", "NAL-R"),
        mold_type=p.get("mold_type", "open"),
        ear=p.get("ear", "left"),
        detect_feedback=False,
    )
    return jsonify({
        "report": _report_to_dict(res.report),
        "std_freqs": STD_FREQS.tolist(),
        "audiogram": {
            "freqs": ag.freqs.tolist(),
            "left_hl": ag.left_hl.tolist(),
            "right_hl": ag.right_hl.tolist(),
        },
    })


def _wav_bytes(y: np.ndarray, fs: int) -> io.BytesIO:
    buf = io.BytesIO()
    audio.save_wav(buf, y, fs)
    buf.seek(0)
    return buf


@app.post("/api/process")
def process_audio():
    """上传录音 → 返回裸耳/助听两个 WAV（multipart 两段文件）+ JSON 报告。"""
    p = request.form
    ag = Audiogram(
        np.asarray([float(v) for v in p.getlist("freqs")], dtype=float),
        np.asarray([float(v) for v in p.getlist("left_hl")], dtype=float),
        np.asarray([float(v) for v in p.getlist("right_hl")], dtype=float),
    )
    upload = request.files.get("audio")
    if upload is not None and upload.filename:
        x, fs = audio.load_mono(upload.stream)
        # 统一到 24 kHz 处理采样率，降低长音频计算量
        if fs != 24000:
            from scipy import signal as sg
            n = int(round(len(x) * 24000 / fs))
            x = sg.resample(x, n)
            fs = 24000
    else:
        fs = 24000
        rng = np.random.default_rng(int(p.get("demo_seed", 1)))
        x = synth.speech_like_signal(float(p.get("demo_seconds", 8)), fs, rng)
        if p.get("inject_howl") == "1":
            x = synth.inject_howl(x, fs)

    res = engine.process(
        x, fs, ag,
        formula=p.get("formula", "NAL-R"),
        mold_type=p.get("mold_type", "open"),
        ear=p.get("ear", "left"),
        detect_feedback=p.get("detect_feedback", "1") == "1",
        smearing=p.get("smearing", "1") == "1",
    )

    token = uuid.uuid4().hex[:12]
    unaided_buf = _wav_bytes(res.unaided, fs)
    aided_buf = _wav_bytes(res.aided, fs)
    boundary = f"----hsim{token}"
    lines = []
    lines.append(f"--{boundary}".encode())
    lines.append(b'Content-Disposition: form-data; name="report"; filename="report.json"')
    lines.append(b"Content-Type: application/json")
    lines.append(b"")
    import json
    lines.append(json.dumps(_report_to_dict(res.report), ensure_ascii=False).encode("utf-8"))
    for name, buf in (("unaided", unaided_buf), ("aided", aided_buf)):
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"; filename="{name}.wav"'.encode())
        lines.append(b"Content-Type: audio/wav")
        lines.append(b"")
        lines.append(buf.read())
    lines.append(f"--{boundary}--".encode())
    body = b"\r\n".join(lines)
    from flask import Response
    return Response(body, mimetype=f"multipart/form-data; boundary={boundary}")


@app.get("/api/demo-signal")
def demo_signal():
    """直接下载内置类言语演示信号 WAV。"""
    fs = 24000
    rng = np.random.default_rng(2)
    x = synth.speech_like_signal(8.0, fs, rng)
    return send_file(_wav_bytes(x, fs), mimetype="audio/wav",
                     as_attachment=True, download_name="demo_speech.wav")


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
