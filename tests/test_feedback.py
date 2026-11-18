"""验收指标（啸叫）：频点自动找出并压下去。"""

import numpy as np

from hearing_aid_sim.audio_io import pure_tone, speech_shaped_noise
from hearing_aid_sim.config import DEFAULT_SR
from hearing_aid_sim.feedback import (AdaptiveFeedbackCanceller, HowlDetector,
                                      apply_notches, erle_db,
                                      simulate_feedback_path, notch_depth)
from hearing_aid_sim.spectral import stft
from hearing_aid_sim.engine import HearingAidEngine


def _tone_plus_speech(sr, howl_hz=3150.0, howl_db=78.0):
    rng = np.random.default_rng(11)
    speech = speech_shaped_noise(sr * 2, sr, 60.0, rng)
    tone = pure_tone(howl_hz, sr, howl_db, n=len(speech))
    return speech + tone


def test_detector_finds_persistent_howl(sr):
    x = _tone_plus_speech(sr)
    spec, freqs, _ = stft(x, sr)
    power_db = 20 * np.log10(np.maximum(np.abs(spec), 1e-10))
    howls = HowlDetector(freqs, sr / 256).detect(power_db)
    assert len(howls) >= 1
    found = min(abs(h.freq_hz - 3150.0) for h in howls)
    assert found < 100.0                  # 频点定位误差 <100 Hz


def test_detector_ignores_broadband_speech(sr):
    """没有持续纯音时不得误报啸叫。"""
    rng = np.random.default_rng(12)
    x = speech_shaped_noise(sr * 2, sr, 65.0, rng)
    spec, freqs, _ = stft(x, sr)
    power_db = 20 * np.log10(np.maximum(np.abs(spec), 1e-10))
    howls = HowlDetector(freqs, sr / 256).detect(power_db)
    assert howls == []


def _relative_notch_depth_db(sig, sr, target_hz=3150.0):
    """目标频点相对邻域中值的凹陷深度（dB，正值=有陷波）。"""
    spec, freqs, _ = stft(sig, sr)
    power = np.mean(np.abs(spec) ** 2, axis=0)
    k = int(np.argmin(np.abs(freqs - target_hz)))
    neigh = np.concatenate([np.arange(k - 6, k - 2), np.arange(k + 3, k + 7)])
    return 10 * np.log10(np.median(power[neigh]) / (power[k] + 1e-20) + 1e-20)


def test_notch_suppresses_howl_by_at_least_10db(sr):
    x = _tone_plus_speech(sr)
    spec, freqs, _ = stft(x, sr)
    power_db = 20 * np.log10(np.maximum(np.abs(spec), 1e-10))
    howls = HowlDetector(freqs, sr / 256).detect(power_db)
    y = apply_notches(x, sr, howls)
    # 陷波后相对凹陷比输入时深至少 10 dB
    assert _relative_notch_depth_db(y, sr) - _relative_notch_depth_db(x, sr) >= 10.0


def test_notch_depth_adapts_to_prominence():
    assert notch_depth(10.0) == -6.0
    assert notch_depth(25.0) == -24.0
    assert -24.0 < notch_depth(16.0) < -6.0


def test_afc_echo_return_loss_enhancement(sr):
    """NLMS 自适应抵消：合成反馈路径上 ERLE 应超过 10 dB。"""
    rng = np.random.default_rng(13)
    n = sr // 2
    h = simulate_feedback_path(64, sr, peak_hz=2800.0, rng=rng)
    source = speech_shaped_noise(n, sr, 60.0, rng)
    mic = np.convolve(source, h)[:n] + source * 0.0   # 纯回声场景
    afc = AdaptiveFeedbackCanceller(n_taps=64, mu=0.1)
    err = afc.process_block(mic, source)
    # 只统计收敛后的后半段
    erle = erle_db(mic[n // 2:], err[n // 2:])
    assert erle > 10.0, f"ERLE 不足：{erle:.1f} dB"


def test_afc_closed_loop_stays_bounded(sr):
    """闭环（含正反馈回路）不发散，输出保持有限且幅度受控。"""
    rng = np.random.default_rng(14)
    h = simulate_feedback_path(64, sr, gain_db=-3.0, peak_hz=3300.0,
                               rng=rng)
    source = speech_shaped_noise(sr // 2, sr, 55.0, rng)
    ag = __import__("hearing_aid_sim.audiogram", fromlist=["Audiogram"]).Audiogram
    eng = HearingAidEngine(ag.standard(np.full(9, 40.0)), sr=sr)
    y, _ = eng.process_with_afc(source, h, n_taps=64, mu=0.08)
    assert np.all(np.isfinite(y))
    assert np.max(np.abs(y)) < 2.0


def test_end_to_end_howl_suppressed_in_engine(sr):
    """整机通路：含啸叫的录音处理后，3150 Hz 相对邻域的陷波深度 >=10 dB。"""
    x = _tone_plus_speech(sr)
    ag = __import__("hearing_aid_sim.audiogram", fromlist=["Audiogram"]).Audiogram
    eng = HearingAidEngine(ag.standard(np.full(9, 45.0)), sr=sr,
                           coupling="open")
    y = eng.process_aided(x)
    assert len(eng.howls) >= 1
    assert _relative_notch_depth_db(y, sr) - _relative_notch_depth_db(x, sr) >= 10.0
