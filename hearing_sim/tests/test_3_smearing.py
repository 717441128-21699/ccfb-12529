"""需求 3: 模拟听损时高频不只是变小, 言语清晰度下降也要可听出来。

机制是 Baer & Moore (1993) 频谱展宽: 耳蜗频率分辨力下降使相邻谱峰/谱谷
被抹平。验收从"频谱对比度"这一可量化的清晰度代理指标入手:
- 展宽后谱峰谷对比度显著下降;
- 高频(重损区)展宽因子大于低频;
- 展宽保持总能量 (矩阵逐行归一化), 即"不是单纯变小";
- 两条邻近谱峰展宽后可分辨间距变大 (分辨力丧失的直接体现);
- 正常听力几乎不展宽, 重度聋展宽最强。
"""
import numpy as np
import pytest

from hearing_sim import ENGINE_FS
from hearing_sim.audiogram import (
    preset_normal, preset_presbycusis, preset_steep_slope,
)
from hearing_sim.engine import FittingEngine, EngineConfig, stft, istft, N_FFT, HOP
from hearing_sim.smearing import erb_hz, smearing_factors, smearing_matrix


def spectral_contrast(mag: np.ndarray, active_frac: float = 0.5) -> float:
    """谱对比度 (dB): 只在有能量的活跃 bin 上取峰(95)/谷(25)分位之差。

    排除无信号噪声底, 否则全局 5 分位会落到 -160 dB 使指标失真。
    """
    db = 20.0 * np.log10(np.maximum(mag, 1e-8))
    flat = db.flatten()
    thresh = np.percentile(flat, 100 * (1 - active_frac))
    active = flat[flat >= thresh]
    return float(np.percentile(active, 95) - np.percentile(active, 25))


def test_erb_formula():
    """Glasberg-Moore ERB: 1 kHz 约 132 Hz。"""
    assert abs(erb_hz(1000.0) - 132.24) < 0.5


def test_smearing_factor_increases_with_loss():
    """展宽因子随听阈增大: 正常听力≈1, 重度聋高频接近 6。"""
    f = np.array([250.0, 1000.0, 4000.0, 6000.0])
    f_normal = smearing_factors(preset_normal(), f)
    f_steep = smearing_factors(preset_steep_slope(), f)
    np.testing.assert_allclose(f_normal, 1.0, atol=0.1)
    # 陡降型低频正常(因子1), 高频重度(因子>5)
    assert f_steep[0] == 1.0
    assert f_steep[-1] > 5.0
    # 同一重度高频点, 陡降型展宽远强于正常听力
    assert f_steep[-1] > f_normal[-1] + 4.0


def test_smearing_matrix_preserves_energy():
    """展宽矩阵逐行归一化, 总能量保持 (区分于单纯衰减)。"""
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / ENGINE_FS)
    factors = smearing_factors(preset_presbycusis(), freqs)
    mat = smearing_matrix(freqs, factors)
    row_sums = mat.sum(axis=1)
    np.testing.assert_allclose(row_sums, 1.0, atol=1e-10)


def test_smearing_reduces_spectral_contrast():
    """核心: 展宽后谱峰谷对比度显著下降 (言语清晰度降低的物理本质)。"""
    fs = ENGINE_FS
    n = fs * 2
    t = np.arange(n) / fs
    # 两个邻近高频谱峰 (模拟共振峰), 强对比度
    x = (0.3 * np.sin(2 * np.pi * 3000 * t) + 0.3 * np.sin(2 * np.pi * 3600 * t)).astype(np.float32)

    eng = FittingEngine(preset_steep_slope(), fs, EngineConfig(enable_feedback=False))
    spec, win = stft(x)
    mag_in = np.abs(spec)

    mag_smeared = mag_in @ eng.loss_params["smear_matrix"].T
    c_in = spectral_contrast(mag_in)
    c_out = spectral_contrast(mag_smeared)
    assert c_out < c_in * 0.8, f"对比度下降不足: {c_in:.1f} -> {c_out:.1f} dB"


def test_adjacent_peaks_become_unresolvable():
    """两邻近谱峰展宽后峰间谷被填浅 (分辨力丧失)。"""
    fs = ENGINE_FS
    n = fs * 2
    t = np.arange(n) / fs
    x = (0.3 * np.sin(2 * np.pi * 3200 * t) + 0.3 * np.sin(2 * np.pi * 3500 * t)).astype(np.float32)
    eng = FittingEngine(preset_steep_slope(), fs, EngineConfig(enable_feedback=False))
    spec, _ = stft(x)
    mag_in = np.abs(spec)
    mag_out = mag_in @ eng.loss_params["smear_matrix"].T
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / fs)
    band = (freqs >= 2800) & (freqs <= 3900)
    # 谷深 = 峰值 - 谷值; 展宽后谷应变浅
    valley_in = np.min(mag_in[:, band]) / np.max(mag_in[:, band])
    valley_out = np.min(mag_out[:, band]) / np.max(mag_out[:, band])
    assert valley_out > valley_in


def test_unaided_path_actually_smears():
    """端到端: 助听前输出相对输入, 高频谱对比度下降 (展宽确实作用于信号)。"""
    fs = ENGINE_FS
    n = fs * 2
    t = np.arange(n) / fs
    x = (0.2 * np.sin(2 * np.pi * 250 * t)
         + 0.2 * np.sin(2 * np.pi * 3000 * t)
         + 0.2 * np.sin(2 * np.pi * 3600 * t)).astype(np.float32)
    eng = FittingEngine(preset_presbycusis(), fs, EngineConfig(enable_feedback=False))
    y = eng.process_unaided(x)
    spec_in, _ = stft(x)
    spec_out, _ = stft(y)
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / fs)
    hf = freqs >= 2000
    c_in = spectral_contrast(np.abs(spec_in)[:, hf])
    c_out = spectral_contrast(np.abs(spec_out)[:, hf])
    assert c_out < c_in


def test_smearing_toggle_changes_output():
    """关闭展宽时输出与开启时不同, 证明清晰度下降来自该模块而非其他环节。"""
    fs = ENGINE_FS
    n = fs * 2
    rng = np.random.default_rng(5)
    x = (rng.standard_normal(n) * 0.2).astype(np.float32)
    ag = preset_presbycusis()
    y_on = FittingEngine(ag, fs, EngineConfig(enable_smearing=True,
                       enable_feedback=False)).process_unaided(x)
    y_off = FittingEngine(ag, fs, EngineConfig(enable_smearing=False,
                        enable_feedback=False)).process_unaided(x)
    assert np.max(np.abs(y_on - y_off)) > 1e-4
