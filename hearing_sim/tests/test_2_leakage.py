"""需求 2: 耳模开放与封闭两种情况下, 低频泄漏的增益自动补偿。

验收:
- 开放耳塞泄漏高通截止 ~500 Hz, 封闭耳模 ~150 Hz, 曲线形态符合文献;
- 250/500 Hz 开放态泄漏显著, 补偿器自动追加增益;
- 高频几乎不受泄漏影响;
- 补偿受反馈余量约束, 超出部分作为残余泄漏如实上报 (开放耳的真实临床限制);
- 引擎实际使用补偿后的目标, 且封闭态残余泄漏小于开放态。
"""
import numpy as np
import pytest

from hearing_sim import ENGINE_FS
from hearing_sim.audiogram import preset_presbycusis
from hearing_sim.engine import FittingEngine, EngineConfig
from hearing_sim.filterbank import CENTER_FREQS
from hearing_sim.leakage import (
    FITTING_CLOSED, FITTING_OPEN, VENT_FC, compensate_gains, vent_response_db,
)
from hearing_sim.prescription import nalr_gains

FS = ENGINE_FS


def test_vent_cutoff_frequencies_match_literature():
    """开放 ~500 Hz、封闭 ~150 Hz 的高通截止, -3 dB 点落在截止频率附近。"""
    assert VENT_FC[FITTING_OPEN] == 500.0
    assert VENT_FC[FITTING_CLOSED] == 150.0
    for fitting, fc in VENT_FC.items():
        db_at_fc = vent_response_db(np.array([fc]), fitting)[0]
        # 二阶高通在 fc 处约 -3 dB (本模型 r=1 时 mag=1/sqrt(2))
        assert abs(db_at_fc - (-3.01)) < 0.1


def test_open_leaks_more_low_freq_than_closed():
    """同一低频, 开放态泄漏衰减量必须大于封闭态。"""
    freqs = np.array([250.0, 500.0])
    loss_open = -vent_response_db(freqs, FITTING_OPEN)
    loss_closed = -vent_response_db(freqs, FITTING_CLOSED)
    np.testing.assert_array_less(loss_closed, loss_open)


def test_high_freq_not_affected_by_leakage():
    """2 kHz 以上泄漏衰减应接近 0 (通气孔对高频无影响)。"""
    hf = np.array([2000.0, 4000.0, 6000.0])
    for fitting in (FITTING_OPEN, FITTING_CLOSED):
        loss = -vent_response_db(hf, fitting)
        np.testing.assert_array_less(loss, 0.5)


def test_open_fitting_auto_compensates_low_frequency():
    """开放验配: 250/500 Hz 被自动追加补偿增益, 高频不补偿。"""
    base = nalr_gains(preset_presbycusis())
    res = compensate_gains(base, CENTER_FREQS, FITTING_OPEN, feedback_margin=6.0)
    # 低频补偿为正
    assert res["compensation_db"][0] > 4.0   # 250 Hz
    assert res["compensation_db"][1] > 1.0   # 500 Hz
    # 高频补偿趋零
    assert np.all(res["compensation_db"][4:] < 0.5)
    # 补偿后增益不小于原目标
    np.testing.assert_array_less(base - 0.01, res["compensated_gains"])


def test_compensation_capped_by_feedback_margin():
    """反馈余量限制: 开放耳 250 Hz 泄漏 > 余量时, 残余泄漏必须如实上报。"""
    base = nalr_gains(preset_presbycusis())
    margin = 6.0
    res = compensate_gains(base, CENTER_FREQS, FITTING_OPEN, feedback_margin=margin)
    # 补偿绝不超过反馈余量
    np.testing.assert_array_less(res["compensation_db"], margin + 1e-9)
    # 250 Hz 泄漏约 12 dB, 补 6 dB 后仍有残余
    assert res["residual_loss_db"][0] > 0.5
    assert res["stable"] is False


def test_closed_fitting_fully_compensates():
    """封闭耳模泄漏小, 在反馈余量内应能完全补满 (stable=True)。"""
    base = nalr_gains(preset_presbycusis())
    res = compensate_gains(base, CENTER_FREQS, FITTING_CLOSED, feedback_margin=6.0)
    assert np.all(res["residual_loss_db"] < 0.5)
    assert res["stable"] is True


def test_engine_uses_compensated_targets():
    """引擎装配时实际写入压缩器的是补偿后目标, 开放态低频目标高于原始 NAL 目标。"""
    ag = preset_presbycusis()
    base = nalr_gains(ag)
    eng_open = FittingEngine(ag, FS, EngineConfig(formula="NAL-R", fitting=FITTING_OPEN,
                                                  enable_feedback=False))
    eng_closed = FittingEngine(ag, FS, EngineConfig(formula="NAL-R", fitting=FITTING_CLOSED,
                                                    enable_feedback=False))
    # 开放态 250 Hz 补偿量 > 封闭态
    assert eng_open.leakage["compensation_db"][0] > eng_closed.leakage["compensation_db"][0]
    # 引擎 65 dB 目标确实含补偿
    np.testing.assert_allclose(
        eng_open.leakage["compensated_gains"],
        base + eng_open.leakage["compensation_db"], atol=1e-9)
