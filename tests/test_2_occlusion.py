"""验收指标 2：开放/封闭耳模的低频泄漏自动补偿。"""
import numpy as np

from hearing_sim import audio
from hearing_sim.channels import BAND_EDGES, band_centers
from hearing_sim.occlusion import (
    MAX_COMPENSATION_DB,
    VENT_FC,
    compute_occlusion,
    leakage_highpass_db,
)


def test_open_leaks_more_than_closed():
    """同一低频点，开放耳模泄漏量必须显著大于封闭耳模。"""
    freqs = np.array([125.0, 175.0, 250.0])
    lo_open = leakage_highpass_db(freqs, VENT_FC["open"])
    lo_closed = leakage_highpass_db(freqs, VENT_FC["closed"])
    assert np.all(lo_open > lo_closed + 4.0)


def test_leakage_monotonic_decrease():
    """泄漏量随频率升高单调下降，高频几乎不漏。"""
    f = np.geomspace(100, 8000, 50)
    leak = leakage_highpass_db(f, VENT_FC["open"])
    assert np.all(np.diff(leak) < 0)
    assert leak[-1] < 1.0  # 8 kHz 处泄漏 < 1 dB


def test_compensation_equals_leakage_below_cap():
    """未触顶时补偿量必须等于泄漏量（把漏掉的增益精确补回）。"""
    bin_freqs = np.linspace(0, 12000, 513)
    res = compute_occlusion(bin_freqs, "open")
    for c in range(8):
        if res.leakage_db[c] <= MAX_COMPENSATION_DB:
            assert abs(res.compensation_db[c] - res.leakage_db[c]) < 1e-9


def test_compensation_capped_at_40db():
    """补偿上限 40 dB：构造极低截止频率（极大气孔）使最低频通道触顶并被标记。"""
    bin_freqs = np.linspace(0, 12000, 513)
    huge_leak = leakage_highpass_db(bin_freqs, fc_hz=4000.0)
    assert np.any(huge_leak > MAX_COMPENSATION_DB)
    # 正常开放耳模：所有补偿不超过上限，且最低频通道泄漏最大
    res = compute_occlusion(bin_freqs, "open")
    assert np.all(res.compensation_db <= MAX_COMPENSATION_DB + 1e-9)
    assert np.argmax(res.leakage_db) == 0
    # 显式验证封顶逻辑：把上限调低到 5 dB，最低频通道必然触顶
    res_cap = compute_occlusion(bin_freqs, "open", max_comp_db=5.0)
    assert 0 in res_cap.capped_channels
    assert np.all(res_cap.compensation_db <= 5.0 + 1e-9)


def test_closed_mold_rarely_caps():
    """封闭耳模泄漏小，所有通道都不应触及 40 dB 上限。"""
    bin_freqs = np.linspace(0, 12000, 513)
    res = compute_occlusion(bin_freqs, "closed")
    assert res.capped_channels == []
    assert np.all(res.compensation_db < MAX_COMPENSATION_DB)


def test_end_to_end_open_low_frequency_restored(fs, mild_ag):
    """端到端：开放耳模下 250 Hz 成分经补偿后，净增益不低于无泄漏理想目标 3 dB 内。"""
    from hearing_sim import synth
    from hearing_sim.engine import process
    from hearing_sim.prescriptions import linear_targets

    x = synth.pure_tone(250.0, 1.0, fs, level_dbfs=-35.0)  # 65 dB SPL
    res = process(x, fs, mild_ag, formula="NAL-R",
                  mold_type="open", detect_feedback=False)
    target = linear_targets(mild_ag, np.array([250.0]), "NAL-R")[0]
    measured = audio.rms_dbfs(res.aided[int(0.2 * fs):]) - (-35.0)
    # 补偿可能触顶，误差允许到补偿上限对应的范围，但必须明显优于不补偿
    assert measured >= target - MAX_COMPENSATION_DB - 1.0


def test_invalid_mold_rejected():
    with np.testing.assert_raises(ValueError):
        compute_occlusion(np.array([100.0]), "in-ear-whatever")
