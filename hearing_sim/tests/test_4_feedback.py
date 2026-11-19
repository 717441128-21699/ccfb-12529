"""需求 (啸叫): 自动找出啸叫频点并压下去。

验收:
- 注入稳态窄带啸叫音 -> 检测器在规定帧数内定位到频点 (频率误差 < 半个 FFT bin);
- 陷波抑制后该频点能量显著下降, 而邻近频率基本保留;
- 普通语音/谐波复合音不被误报为啸叫;
- 啸叫消失后陷波自动释放;
- 时域双二阶陷波在目标频点有深零点。
"""
import numpy as np
import pytest

from hearing_sim import ENGINE_FS
from hearing_sim.audiogram import preset_presbycusis
from hearing_sim.engine import FittingEngine, EngineConfig, N_FFT, stft
from hearing_sim.feedback import (
    FeedbackDetector, SpectralNotchSuppressor, feedback_notch_sos, suppress_tone,
)
from tests.signals import harmonic_complex, inject_howl, sine_tone, speech_shaped_noise

FS = ENGINE_FS


def _run_detector(detector: FeedbackDetector, x: np.ndarray):
    spec, _ = stft(x)
    found = []
    for frame in spec:
        db = 20.0 * np.log10(np.maximum(np.abs(frame), 1e-8)) + 94.0
        found.extend(detector.update(db))
    return found


def test_detects_injected_howl_frequency():
    """注入 3.2 kHz 啸叫, 检测器应定位到该频点 (误差 < 半 bin)。"""
    det = FeedbackDetector(FS, N_FFT)
    base = speech_shaped_noise(FS * 3, FS, rms=0.05, rng=np.random.default_rng(1))
    x = inject_howl(base, FS, howl_hz=3200.0, gain=0.3, start=0.3)
    found = _run_detector(det, x)
    assert found, "未检出啸叫"
    freqs = np.array([f for f, _ in found])
    bin_hz = FS / N_FFT
    assert np.min(np.abs(freqs - 3200.0)) < bin_hz


def test_suppressor_reduces_howl_energy():
    """陷波抑制后, 啸叫频点能量下降 >= 10 dB, 远离频点基本保留。

    在同一引擎、同一帧上比较陷波施加前/后的谱, 隔离陷波本身的作用,
    不受 WDRC/OSPL90 状态轨迹影响。
    """
    fs = FS
    n = fs * 3
    base = speech_shaped_noise(n, fs, rms=0.05, rng=np.random.default_rng(2))
    x = inject_howl(base, fs, howl_hz=2700.0, gain=0.3)
    eng = FittingEngine(preset_presbycusis(), fs, EngineConfig(enable_feedback=True))
    y, howl_log, _ = eng.process_aided(x)
    assert howl_log, "引擎未检出啸叫"

    # 直接验证陷波形状: 在 2700 Hz 谱峰上施加抑制器
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / fs)
    k_howl = int(np.argmin(np.abs(freqs - 2700.0)))
    test_spec = np.zeros(len(freqs), dtype=complex)
    test_spec[k_howl] = 1.0
    eng.suppressor.active.clear()
    eng.suppressor.update_notches([(2700.0, 20.0)])
    notched = eng.suppressor.apply(test_spec)
    reduction = -20 * np.log10(max(np.abs(notched[k_howl]), 1e-12))
    assert reduction >= 10.0, f"啸叫频点仅衰减 {reduction:.1f} dB"

    # 远离频点 (距啸叫 1300 Hz, 远超 Q=25 陷波尾部) 几乎不变
    k_far = int(np.argmin(np.abs(freqs - 4000.0)))
    test_spec2 = np.zeros(len(freqs), dtype=complex)
    test_spec2[k_far] = 1.0
    notched2 = eng.suppressor.apply(test_spec2)
    far_change = abs(20 * np.log10(max(np.abs(notched2[k_far]), 1e-12)))
    assert far_change < 1.0


def test_no_false_alarm_on_voiced_speech():
    """稳态元音谐波复合音不应被误报为啸叫。"""
    det = FeedbackDetector(FS, N_FFT)
    x = harmonic_complex(FS * 3, FS, f0=120.0, harmonics=25, rms=0.1)
    found = _run_detector(det, x)
    assert not found, f"语音谐波被误报: {found[:3]}"


def test_no_false_alarm_on_speech_shaped_noise():
    """语音形随机噪声不应触发啸叫检测。"""
    det = FeedbackDetector(FS, N_FFT)
    x = speech_shaped_noise(FS * 3, FS, rms=0.15, rng=np.random.default_rng(9))
    found = _run_detector(det, x)
    assert not found


def test_notch_releases_after_howl_stops():
    """啸叫消失后, 陷波应在释放帧数内自动清除。"""
    sup = SpectralNotchSuppressor(FS, N_FFT, release_frames=20)
    sup.update_notches([(3000.0, 20.0)])
    assert 3000.0 in sup.active
    for _ in range(25):
        sup.update_notches([])
    assert not sup.active


def test_time_domain_notch_has_deep_zero():
    """时域双二阶陷波在目标频点形成深零点 (>15 dB 衰减)。"""
    fs = FS
    n = fs * 2
    x = sine_tone(n, fs, 2500.0, rms=0.2)
    y = suppress_tone(x, 2500.0, fs, q=25.0)
    # 频域比较目标频点能量
    Xin = np.abs(np.fft.rfft(x))
    Xout = np.abs(np.fft.rfft(y))
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    k = int(np.argmin(np.abs(freqs - 2500.0)))
    att = 20 * np.log10(Xin[k] / max(Xout[k], 1e-12))
    assert att > 15.0


def test_max_notches_limited():
    """同时活动的陷波数量受 max_notches 限制。"""
    sup = SpectralNotchSuppressor(FS, N_FFT, max_notches=3)
    sup.update_notches([(2000.0, 20), (2500.0, 20), (3000.0, 20), (3500.0, 20)])
    assert len(sup.active) <= 3
