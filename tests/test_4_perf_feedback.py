"""验收指标 4：1 分钟录音处理 ≤ 2 秒；以及啸叫检测/抑制链路测试。"""
import time

import numpy as np

from hearing_sim import audio, feedback as fb_mod
from hearing_sim.audiogram import Audiogram
from hearing_sim.channels import band_centers
from hearing_sim.engine import benchmark, process
from hearing_sim.prescriptions import linear_targets
from hearing_sim.synth import inject_howl, speech_like_signal


# ---------------------------------------------------------------- 性能
def test_60s_processing_under_2s():
    """60 秒类言语信号，裸耳+助听双链路总耗时 ≤ 2 秒。"""
    result = benchmark(fs=24000, duration_s=60.0)
    assert result["processing_seconds"] <= 2.0, (
        f"耗时 {result['processing_seconds']:.2f}s，超过 2s 目标"
    )
    assert result["realtime_ratio"] >= 30.0


def test_benchmark_report_structure():
    result = benchmark(fs=24000, duration_s=5.0)
    assert {"duration_s", "processing_seconds",
            "realtime_ratio", "meets_2s_target"} <= set(result)


# ---------------------------------------------------------------- 啸叫检测
def test_detect_injected_howls(fs):
    """注入 2.7k/4.3k 啸叫后必须都被检出，频率误差 ≤ 60 Hz。"""
    rng = np.random.default_rng(5)
    x = speech_like_signal(3.0, fs, rng)
    x = inject_howl(x, fs, howl_freqs_hz=(2700.0, 4300.0), level_dbfs=-10.0)
    f, _, Z = audio.stft(x, fs)
    howls = fb_mod.detect_howl(Z, f)
    found = sorted(h.freq_hz for h in howls)
    assert len(found) >= 2
    assert any(abs(h - 2700) < 60 for h in found)
    assert any(abs(h - 4300) < 60 for h in found)


def test_clean_speech_no_false_alarm(fs):
    """正常类言语信号不应误报啸叫。"""
    rng = np.random.default_rng(6)
    x = speech_like_signal(4.0, fs, rng)
    f, _, Z = audio.stft(x, fs)
    assert fb_mod.detect_howl(Z, f) == []


def test_notch_suppresses_howl(fs):
    """陷波后啸叫频点能量至少下降 15 dB，邻近 500 Hz 外言语频点损伤 < 3 dB。"""
    rng = np.random.default_rng(7)
    x = speech_like_signal(3.0, fs, rng)
    x = inject_howl(x, fs, howl_freqs_hz=(3000.0,), level_dbfs=-10.0)
    f, _, Z0 = audio.stft(x, fs)
    y = fb_mod.apply_notches(x, fs, [3000.0])
    _, _, Z1 = audio.stft(y, fs)

    def band_energy(Z, lo, hi):
        sel = (f >= lo) & (f <= hi)
        return np.sum(np.abs(Z[sel, :]) ** 2)

    e_before = band_energy(Z0, 2960, 3040)
    e_after = band_energy(Z1, 2960, 3040)
    suppression = 10 * np.log10(e_before / max(e_after, 1e-18))
    assert suppression >= 15.0

    neighbor_before = band_energy(Z0, 2400, 2500)
    neighbor_after = band_energy(Z1, 2400, 2500)
    collateral = 10 * np.log10(neighbor_after / max(neighbor_before, 1e-18))
    assert abs(collateral) < 3.0


def test_suppress_pipeline_end_to_end(fs):
    rng = np.random.default_rng(8)
    x = speech_like_signal(3.0, fs, rng)
    x = inject_howl(x, fs, howl_freqs_hz=(2700.0,), level_dbfs=-10.0)
    f, _, Z = audio.stft(x, fs)
    y, result = fb_mod.suppress_feedback(x, fs, Z, f)
    assert len(result.howls) >= 1
    assert np.any(result.channel_cuts_db > 0)
    # 陷波器必须稳定：输出能量不得超过输入能量的 2 倍（滤波器不爆炸）
    assert np.sqrt(np.mean(y**2)) < 2.0 * np.sqrt(np.mean(x**2))
    assert np.isfinite(y).all()


# ---------------------------------------------------------------- 稳定余量
def test_auto_stabilize_cuts_unsafe_channel():
    """目标增益超过临界增益的通道必须被自动削减到满足 6 dB 余量。"""
    targets = np.array([30, 35, 40, 45, 50, 55, 60, 65], dtype=float)
    stable, cuts = fb_mod.auto_stabilize(targets)
    margin = fb_mod.stability_margin(stable)
    assert np.all(margin >= 6.0 - 1e-9)
    assert np.any(cuts > 0)
    # 安全通道不动
    safe = fb_mod.stability_margin(targets) >= 6.0
    assert np.allclose(stable[safe], targets[safe])


def test_engine_report_flags_howl(fs, mild_ag):
    rng = np.random.default_rng(9)
    x = speech_like_signal(3.0, fs, rng)
    x = inject_howl(x, fs, howl_freqs_hz=(3500.0,), level_dbfs=-8.0)
    res = process(x, fs, mild_ag)
    assert res.report.feedback is not None
    assert len(res.report.feedback.howls) >= 1
