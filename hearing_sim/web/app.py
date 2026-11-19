"""助听器验配模拟 Web 服务。

页面: GET /            单页应用 (录入听力图、上传录音、A/B 试听、查看验配报告)
API:
  POST /api/prescription  按听力图 + 公式 + 耳模形式返回 8 通道目标/压缩/泄漏补偿
  POST /api/process       上传录音, 返回助听前/助听后两个 wav 与验配报告
  GET  /api/calibration   1 kHz 校准音 wav
"""
from __future__ import annotations

import io
import os
import tempfile
import time
import uuid

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from hearing_sim import ENGINE_FS
from hearing_sim.audiogram import STD_FREQS, Audiogram
from hearing_sim.engine import EngineConfig, FittingEngine
from hearing_sim.io_audio import load_audio
from hearing_sim.calibration import calibration_tone

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="助听器验配模拟", version="1.0.0")
app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")


def _parse_audiogram(losses: str) -> Audiogram:
    vals = [float(v) for v in losses.split(",")]
    if len(vals) != len(STD_FREQS):
        raise ValueError(f"需要 {len(STD_FREQS)} 个频率点, 收到 {len(vals)}")
    return Audiogram.standard(vals)


def _wav_bytes(x: np.ndarray, fs: int) -> bytes:
    buf = io.BytesIO()
    peak = np.max(np.abs(x)) if x.size else 0.0
    if peak > 0.99:
        x = x * (0.99 / peak)
    sf.write(buf, x.astype(np.float32), fs, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with open(os.path.join(WEB_DIR, "static", "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/calibration")
def calibration() -> Response:
    tone = calibration_tone(ENGINE_FS)
    return Response(content=_wav_bytes(tone, ENGINE_FS), media_type="audio/wav")


@app.post("/api/prescription")
def prescription(
    losses: str = Form(...),
    formula: str = Form("WDRC"),
    fitting: str = Form("open"),
) -> JSONResponse:
    ag = _parse_audiogram(losses)
    cfg = EngineConfig(formula=formula, fitting=fitting, enable_feedback=False)
    eng = FittingEngine(ag, ENGINE_FS, cfg)
    return JSONResponse({
        "freqs_hz": STD_FREQS.tolist(),
        "channel_centers_hz": eng.targets["freqs"].tolist(),
        "audiogram_loss_dbhl": ag.losses.tolist(),
        "formula": formula,
        "fitting": fitting,
        "target_gains_db": [round(float(g), 2) for g in eng.leakage["compensated_gains"]],
        "base_gains_db": [round(float(g), 2) for g in eng.targets["gains65"]],
        "compression_ratios": [round(float(c), 2) for c in eng.targets["compression_ratios"]],
        "vent_loss_db": [round(float(v), 2) for v in eng.leakage["vent_loss_db"]],
        "compensation_db": [round(float(v), 2) for v in eng.leakage["compensation_db"]],
        "residual_loss_db": [round(float(v), 2) for v in eng.leakage["residual_loss_db"]],
        "leakage_stable": eng.leakage["stable"],
        "severity": ag.severity,
        "pta4": round(ag.pta4, 1),
    })


@app.post("/api/process")
async def process(
    audio: UploadFile = File(...),
    losses: str = Form(...),
    formula: str = Form("WDRC"),
    fitting: str = Form("open"),
    feedback: bool = Form(True),
    smearing: bool = Form(True),
) -> JSONResponse:
    ag = _parse_audiogram(losses)
    cfg = EngineConfig(
        formula=formula, fitting=fitting,
        enable_feedback=feedback, enable_smearing=smearing,
    )

    # 保存上传文件到临时目录 (隔离, 不在解释器目录落地不可信文件)
    suffix = os.path.splitext(audio.filename or "in.wav")[1] or ".wav"
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, f"in_{uuid.uuid4().hex}{suffix}")
        with open(in_path, "wb") as f:
            f.write(await audio.read())
        x, fs = load_audio(in_path, ENGINE_FS)

    eng = FittingEngine(ag, fs, cfg)
    t0 = time.perf_counter()
    result = eng.process(x)
    elapsed = time.perf_counter() - t0

    return JSONResponse({
        "duration_s": round(len(x) / fs, 3),
        "elapsed_s": round(elapsed, 3),
        "realtime_factor": round(elapsed / (len(x) / fs), 4),
        "fs": fs,
        "severity": ag.severity,
        "pta4": round(ag.pta4, 1),
        "fitting": fitting,
        "formula": formula,
        "target_gains_db": [round(float(g), 2) for g in eng.leakage["compensated_gains"]],
        "compression_ratios": [round(float(c), 2) for c in eng.targets["compression_ratios"]],
        "vent_loss_db": [round(float(v), 2) for v in eng.leakage["vent_loss_db"]],
        "compensation_db": [round(float(v), 2) for v in eng.leakage["compensation_db"]],
        "residual_loss_db": [round(float(v), 2) for v in eng.leakage["residual_loss_db"]],
        "leakage_stable": eng.leakage["stable"],
        "howl_count": len(result.detected_howls),
        "howl_freqs_hz": sorted({round(f, 1) for _, f, _ in result.detected_howls}),
        "unaided_url": _save_variant(result.unaided, fs, ag, cfg, "unaided"),
        "aided_url": _save_variant(result.aided, fs, ag, cfg, "aided"),
    })


# 临时产物目录 (进程内保存两个试听版本, 供前端拉取)
_OUTPUT: dict[str, bytes] = {}


def _save_variant(x: np.ndarray, fs: int, ag: Audiogram, cfg: EngineConfig, tag: str) -> str:
    key = f"{uuid.uuid4().hex}_{tag}.wav"
    _OUTPUT[key] = _wav_bytes(x, fs)
    return f"/api/audio/{key}"


@app.get("/api/audio/{key}")
def get_audio(key: str) -> Response:
    data = _OUTPUT.get(key)
    if data is None:
        return JSONResponse({"error": "音频已过期或不存在"}, status_code=404)
    return Response(content=data, media_type="audio/wav")
