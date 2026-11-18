"""验收指标 4：一分钟录音处理耗时不超过 2 秒。

同时覆盖 STFT 完全重构、两个版本的整体冒烟与 CLI 入口。
"""

import time

import numpy as np

from hearing_aid_sim.audio_io import speech_shaped_noise
from hearing_aid_sim.engine import HearingAidEngine, process_aided, process_unaided
from hearing_aid_sim.spectral import istft, stft


def test_stft_perfect_reconstruction(speech_65, sr):
    spec, _, win = stft(speech_65, sr)
    x_back = istft(spec, sr, length=len(speech_65))
    err = np.max(np.abs(x_back - speech_65))
    assert err < 1e-9


def test_one_minute_aided_under_2_seconds(sloping_ag, sr):
    rng = np.random.default_rng(21)
    x = speech_shaped_noise(60 * sr, sr, 65.0, rng)
    eng = HearingAidEngine(sloping_ag, sr=sr, coupling="open")
    t0 = time.perf_counter()
    y = eng.process_aided(x)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"戴机处理耗时 {elapsed:.2f}s 超过 2s"
    assert len(y) == len(x)
    assert np.all(np.isfinite(y))


def test_one_minute_unaided_under_2_seconds(sloping_ag, sr):
    rng = np.random.default_rng(22)
    x = speech_shaped_noise(60 * sr, sr, 65.0, rng)
    eng = HearingAidEngine(sloping_ag, sr=sr)
    t0 = time.perf_counter()
    y = eng.process_unaided(x)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"裸耳模拟耗时 {elapsed:.2f}s 超过 2s"
    assert len(y) == len(x)
    assert np.all(np.isfinite(y))


def test_convenience_functions(sloping_ag, sr):
    rng = np.random.default_rng(23)
    x = speech_shaped_noise(sr, sr, 65.0, rng)
    y_a, eng = process_aided(x, sloping_ag, sr=sr)
    y_u = process_unaided(x, sloping_ag, sr=sr)
    assert y_a.shape == x.shape and y_u.shape == x.shape
    # 两个版本确实不同（家属才能听出区别）
    assert not np.allclose(y_a, y_u, atol=1e-3)
