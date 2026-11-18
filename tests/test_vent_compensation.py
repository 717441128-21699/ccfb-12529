"""验收指标 2：开放/封闭耳模低频漏音自动补偿。"""

import numpy as np

from hearing_aid_sim.config import CHANNEL_FREQS
from hearing_aid_sim.coupling import (insertion_loss, vent_compensation,
                                      compensated_targets, MAX_VENT_COMP_DB)
from hearing_aid_sim.engine import HearingAidEngine
from hearing_aid_sim.prescription import target_gain


def test_vent_is_high_pass_low_freq_leaks():
    """漏音是高通效应：低频漏得多、高频漏得少。"""
    il_open = insertion_loss([250, 1000, 4000], "open")
    assert il_open[0] > il_open[1] > il_open[2]
    assert il_open[0] > 10.0                 # 开放耳模 250 Hz 漏 >10 dB
    assert il_open[2] < 3.0                  # 4 kHz 几乎不漏


def test_closed_leaks_far_less_than_open():
    il_open = insertion_loss(CHANNEL_FREQS, "open")
    il_closed = insertion_loss(CHANNEL_FREQS, "closed")
    assert np.all(il_closed < il_open)
    assert il_closed[0] < 6.0                # 封闭耳模最大漏音 <6 dB


def test_compensation_cancels_low_freq_loss(sloping_ag):
    """开放耳模下，低频通道目标增益 = 处方 + 漏音补偿。"""
    raw = target_gain(sloping_ag, CHANNEL_FREQS, "nal-r")
    il = insertion_loss(CHANNEL_FREQS, "open")
    final = compensated_targets(raw, CHANNEL_FREQS, "open")
    added = final - raw
    # 最低两个通道补得最多，且补偿量不超过漏音量（物理可达）
    assert added[0] >= added[2] >= added[-1]
    assert added[0] <= il[0] + 1e-9
    assert added[0] > 8.0                    # 250Hz 附近补 8dB 以上


def test_compensation_capped_for_stability():
    """补偿有物理上限，避免过度增益诱发啸叫。"""
    comp = vent_compensation(CHANNEL_FREQS, "open")
    assert np.all(comp <= MAX_VENT_COMP_DB + 1e-9)


def test_howl_guard_reduces_nearby_compensation():
    """啸叫频点附近，稳定裕量会主动削减补偿。"""
    howl = (3000.0,)
    plain = vent_compensation(CHANNEL_FREQS, "open", ())
    guarded = vent_compensation(CHANNEL_FREQS, "open", howl)
    i = int(np.argmin(np.abs(CHANNEL_FREQS - 3000.0)))
    assert guarded[i] <= plain[i]


def test_end_to_end_open_vs_closed_targets(sloping_ag, speech_65, sr):
    """同一听力图：开放耳模低频通道目标增益显著高于封闭。"""
    eng_open = HearingAidEngine(sloping_ag, sr=sr, coupling="open")
    eng_closed = HearingAidEngine(sloping_ag, sr=sr, coupling="closed")
    diff = eng_open.report.target_db - eng_closed.report.target_db
    assert diff[0] > 6.0                     # 最低频通道差 >6 dB
    assert diff[-1] < 1.0                    # 高频通道几乎无差


def test_open_fitting_measured_gain_reaches_compensated_target(sloping_ag,
                                                                steady_65, sr):
    """端到端：开放耳模实测增益跟上补偿后的目标（3 dB 内，稳态测量）。"""
    eng = HearingAidEngine(sloping_ag, sr=sr, coupling="open")
    y = eng.process_aided(steady_65)
    measured = eng.measure_band_gain(steady_65, y)
    err = np.abs(measured - eng.report.target_db)
    assert np.all(err <= 3.0), f"开放耳模补偿未达标：{np.round(err, 2)}"
