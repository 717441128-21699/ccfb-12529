"""需求 4 (性能): 一分钟录音处理完不超过 2 秒。

实时率 RTF = 处理耗时 / 音频时长, 要求 RTF < 2/60 ≈ 0.0333。
同时校验两条通路输出长度正确、无 NaN/Inf、电平有界。
"""
import time

import numpy as np
import pytest

from hearing_sim import ENGINE_FS
from hearing_sim.audiogram import preset_presbycusis
from hearing_sim.engine import EngineConfig, FittingEngine
from tests.signals import speech_shaped_noise

FS = ENGINE_FS
DURATION_S = 60
RTF_LIMIT = 2.0 / DURATION_S


@pytest.fixture(scope="module")
def long_signal():
    rng = np.random.default_rng(2024)
    return speech_shaped_noise(FS * DURATION_S, FS, rms=0.1, rng=rng)


def test_sixty_second_processing_under_two_seconds(long_signal):
    """60 秒音频 (两条通路) 总处理耗时 < 2 秒。"""
    eng = FittingEngine(preset_presbycusis(), FS, EngineConfig())
    t0 = time.perf_counter()
    result = eng.process(long_signal)
    elapsed = time.perf_counter() - t0
    rtf = elapsed / DURATION_S
    assert elapsed < 2.0, f"耗时 {elapsed:.2f}s 超过 2s (RTF={rtf:.4f})"
    assert rtf < RTF_LIMIT


def test_outputs_well_formed(long_signal):
    """输出长度、数值有效性、电平边界。"""
    eng = FittingEngine(preset_presbycusis(), FS, EngineConfig())
    result = eng.process(long_signal)
    for name, y in (("unaided", result.unaided), ("aided", result.aided)):
        assert len(y) == len(long_signal)
        assert np.all(np.isfinite(y)), f"{name} 含 NaN/Inf"
        assert np.max(np.abs(y)) <= 1.0 + 1e-6, f"{name} 超满刻度"


def test_rtf_margin_with_report(long_signal):
    """打印实测 RTF, 并要求相对 2 秒预算留出至少 15% 余量。"""
    from hearing_sim.pipeline import process_array
    result, _, elapsed = process_array(long_signal, preset_presbycusis(), EngineConfig())
    rtf = elapsed / DURATION_S
    print(f"\n60s 音频处理耗时={elapsed:.3f}s  RTF={rtf:.4f}  预算={RTF_LIMIT:.4f}")
    assert elapsed < 2.0 * 0.85  # 1.7s 以内, 留 15% 余量
