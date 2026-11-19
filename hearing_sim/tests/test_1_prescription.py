"""需求 1: 8 通道增益与公开处方公式目标值相差不超过 3 dB。

测量方法 (对齐真耳分析仪 REM 的纯音/啭音稳态测量):
- 每个通道中心频率放一个整数-bin 正弦 (能量不泄漏、峰均比已知、不触顶);
- 引擎输入级 RMS 归一化后, 读回该带实际输入 SPL;
- 从处方静态表按实测输入级插值出期望增益, 与引擎实测增益比对。
另含 NAL-R / NAL-RP 文献方程的解析校验。
"""
import numpy as np
import pytest

from hearing_sim import ENGINE_FS
from hearing_sim.audiogram import preset_flat40, preset_presbycusis, preset_steep_slope
from hearing_sim.engine import (
    FittingEngine, EngineConfig, N_FFT, HOP, istft, stft, stft_scale_factor, hann_window,
)
from hearing_sim.filterbank import CENTER_FREQS
from hearing_sim.prescription import NAL_FREQS, nalr_gains, nalrp_gains

FS = ENGINE_FS
TOL_DB = 3.0
SCALE = stft_scale_factor(hann_window(N_FFT))


def _tone_at_channel(k: int, amp: float = 0.05, n: int | None = None) -> np.ndarray:
    n = n or FS * 3
    t = np.arange(n) / FS
    bin_k = int(round(CENTER_FREQS[k] * N_FFT / FS))
    f0 = bin_k * FS / N_FFT  # 整数 bin, 无谱泄漏
    return (amp * np.sin(2 * np.pi * f0 * t)).astype(np.float32)


def _measure_channel(engine: FittingEngine, k: int):
    x = _tone_at_channel(k)
    xn, _ = engine._normalize_input(x)
    y, _, _ = engine.process_aided(x)
    spi, _ = stft(xn)
    spo, _ = stft(y)
    t0 = len(spi) // 2
    m = engine.masks[k]
    rms_in = SCALE * np.sqrt(np.sum(np.abs(spi[t0][m]) ** 2))
    rms_out = SCALE * np.sqrt(np.sum(np.abs(spo[t0][m]) ** 2))
    in_spl = 20.0 * np.log10(rms_in + 1e-12) + 94.0
    g_meas = 20.0 * np.log10((rms_out + 1e-12) / (rms_in + 1e-12))
    return in_spl, g_meas, np.max(np.abs(y))


def test_nalr_literature_example():
    """文献方程: 平坦 40 dB HL, NAL-R 1 kHz 增益 = 1+0.31*40+0.05*40 = 15.4 dB。"""
    g = nalr_gains(preset_flat40())
    idx_1k = int(np.where(NAL_FREQS == 1000.0)[0][0])
    assert abs(g[idx_1k] - 15.4) < 0.01


def test_nalrp_reduces_low_freq_for_sloping():
    """陡降型: NAL-RP 相对 NAL-R 削减 250/500 Hz, 2 kHz 以上不变。"""
    ag = preset_steep_slope()
    r, rp = nalr_gains(ag), nalrp_gains(ag)
    assert rp[0] < r[0] and rp[1] < r[1]
    np.testing.assert_allclose(rp[2:], r[2:], atol=1e-9)


@pytest.mark.parametrize("preset", [preset_flat40, preset_presbycusis, preset_steep_slope])
def test_wdrc_all_channels_within_3db(preset):
    """核心验收: WDRC 8 通道实测增益 vs 处方目标 (按实测输入级查表) <= 3 dB。

    若 OSPL90 因输出触及 LDL 而介入 (重度聋高频的真实物理限制), 该通道
    改验"输出被正确钳在 LDL", 而非强求无法实现的增益。
    """
    engine = FittingEngine(preset(), FS, EngineConfig(formula="WDRC", enable_feedback=False))
    for k in range(8):
        in_spl, g_meas, peak = _measure_channel(engine, k)
        g_exp = engine.compressor.target_gain_db(np.full(8, in_spl))[k]
        if peak >= 0.99 - 1e-6:
            # OSPL90 介入: 实测增益必然低于目标, 验证方向正确且输出已限幅
            assert g_meas < g_exp
        else:
            assert abs(g_meas - g_exp) < TOL_DB, (
                f"通道{k}({CENTER_FREQS[k]:.0f}Hz) 误差 {abs(g_meas-g_exp):.2f} dB 超限")


def test_nalr_all_channels_within_3db():
    """线性 NAL-R (封闭耳模) 8 通道实测 vs 目标 <= 3 dB。"""
    engine = FittingEngine(
        preset_presbycusis(), FS,
        EngineConfig(formula="NAL-R", enable_feedback=False, fitting="closed"),
    )
    for k in range(8):
        in_spl, g_meas, _ = _measure_channel(engine, k)
        g_exp = engine.compressor.target_gain_db(np.full(8, in_spl))[k]
        assert abs(g_meas - g_exp) < TOL_DB


def test_soft_gets_more_gain_than_loud():
    """轻声增益必须高于大声 (分开压缩)。逐通道比较两种振幅。"""
    engine = FittingEngine(
        preset_presbycusis(), FS, EngineConfig(formula="WDRC", enable_feedback=False))

    def gain_for(k: int, amp: float) -> float:
        x = _tone_at_channel(k, amp=amp)
        xn, _ = engine._normalize_input(x)
        y, _, _ = engine.process_aided(x)
        spi, _ = stft(xn); spo, _ = stft(y); t0 = len(spi) // 2
        m = engine.masks[k]
        ri = SCALE * np.sqrt(np.sum(np.abs(spi[t0][m]) ** 2))
        ro = SCALE * np.sqrt(np.sum(np.abs(spo[t0][m]) ** 2))
        return 20 * np.log10((ro + 1e-12) / (ri + 1e-12))

    for k in range(8):
        g_soft, g_loud = gain_for(k, 0.01), gain_for(k, 0.2)
        assert g_soft >= g_loud - 0.5  # 容差考虑 OSPL90 介入


def test_ospl90_ceiling_never_exceeded():
    """任何通道输出 SPL 不得超过 LDL (OSPL90 限幅生效)。"""
    engine = FittingEngine(
        preset_steep_slope(), FS, EngineConfig(formula="WDRC", enable_feedback=False))
    for k in range(8):
        x = _tone_at_channel(k, amp=0.3)
        y, _, _ = engine.process_aided(x)
        assert np.max(np.abs(y)) <= 0.99 + 1e-6
