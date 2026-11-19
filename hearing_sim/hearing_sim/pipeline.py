"""高层处理管线: 音频文件 -> 助听前/助听后两个试听版本 + 验配报告数据。"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import numpy as np

from . import ENGINE_FS
from .audiogram import Audiogram
from .calibration import apply_spl_offset
from .engine import EngineConfig, FittingEngine
from .io_audio import duration_s, load_audio, save_audio


@dataclass
class ProcessingReport:
    input_file: str
    duration_s: float
    elapsed_s: float
    realtime_factor: float
    fs: int
    formula: str
    fitting: str
    channel_centers_hz: list
    target_gains_db: list
    compression_ratios: list
    vent_loss_db: list
    compensation_db: list
    residual_loss_db: list
    stable: bool
    detected_howl_count: int
    detected_howl_freqs_hz: list
    severity: str
    pta4: float


def process_file(
    input_path: str,
    audiogram: Audiogram,
    out_unaided_path: str,
    out_aided_path: str,
    config: EngineConfig | None = None,
    fs: int = ENGINE_FS,
    spl_offset_db: float = 0.0,
) -> ProcessingReport:
    """完整处理一个音频文件, 写出两个 wav 并返回报告。"""
    x, fs = load_audio(input_path, fs)
    engine = FittingEngine(audiogram, fs, config)

    t0 = time.perf_counter()
    result = engine.process(x)
    elapsed = time.perf_counter() - t0

    save_audio(out_unaided_path, apply_spl_offset(result.unaided, spl_offset_db), fs)
    save_audio(out_aided_path, apply_spl_offset(result.aided, spl_offset_db), fs)

    howl_freqs = sorted({round(f, 1) for _, f, _ in result.detected_howls})
    from .filterbank import CENTER_FREQS

    return ProcessingReport(
        input_file=input_path,
        duration_s=round(duration_s(x, fs), 3),
        elapsed_s=round(elapsed, 3),
        realtime_factor=round(elapsed / duration_s(x, fs), 4),
        fs=fs,
        formula=engine.cfg.formula,
        fitting=engine.cfg.fitting,
        channel_centers_hz=CENTER_FREQS.tolist(),
        target_gains_db=[round(float(g), 2) for g in engine.leakage["compensated_gains"]],
        compression_ratios=[round(float(c), 2) for c in engine.targets["compression_ratios"]],
        vent_loss_db=[round(float(v), 2) for v in engine.leakage["vent_loss_db"]],
        compensation_db=[round(float(v), 2) for v in engine.leakage["compensation_db"]],
        residual_loss_db=[round(float(v), 2) for v in engine.leakage["residual_loss_db"]],
        stable=engine.leakage["stable"],
        detected_howl_count=len(result.detected_howls),
        detected_howl_freqs_hz=howl_freqs,
        severity=audiogram.severity,
        pta4=round(audiogram.pta4, 1),
    )


def process_array(
    x: np.ndarray, audiogram: Audiogram, config: EngineConfig | None = None, fs: int = ENGINE_FS
):
    """直接对内存数组处理 (测试与实时演示用)。"""
    engine = FittingEngine(audiogram, fs, config)
    t0 = time.perf_counter()
    result = engine.process(x)
    elapsed = time.perf_counter() - t0
    return result, engine, elapsed
