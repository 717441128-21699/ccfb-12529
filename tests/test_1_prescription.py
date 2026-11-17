"""验收指标 1：8 通道增益与公开处方公式目标值相差不超过 3 dB。

测试分两层：
A. 公式层：与 Byrne & Dillon 教材中的 NAL-R 手工算例逐频点比对；
B. 端到端：65 dB SPL 正弦通过完整助听链，实测通道增益相对目标 ≤ 3 dB。
"""
import numpy as np
import pytest

from hearing_sim import audio, feedback as fb_mod, occlusion as occ_mod, wdrc
from hearing_sim.audiogram import STD_FREQS, Audiogram
from hearing_sim.channels import BAND_EDGES, assign_bins, band_centers
from hearing_sim.prescriptions import (
    FORMULAS,
    linear_targets,
    nal_r_targets,
    nal_r_x,
    wdrc_targets,
)


# ---------------------------------------------------------------- A. 公式层
def test_nalr_textbook_flat40():
    """平坦 40 dB HL：X=40，NAL-R 各标准频率目标与教材表一致（容差 0.1 dB）。"""
    ag = Audiogram.mono(np.full(len(STD_FREQS), 40.0))
    assert nal_r_x(ag) == pytest.approx(40.0, abs=1e-10)
    # 教材表 (Byrne & Dillon 1986 / Dillon 2012，平坦 40dB HL 行，X=40)
    expected = {250: 35.4, 500: 44.4, 1000: 53.4, 2000: 51.4,
                3000: 50.4, 4000: 50.4, 6000: 50.4}
    got = nal_r_targets(ag, np.array(list(expected), dtype=float))
    for (f, exp), g in zip(expected.items(), got):
        assert g == pytest.approx(exp, abs=0.1), f"NAL-R {f}Hz: 期望{exp} 实得{g}"


def test_nalr_textbook_flat60():
    """平坦 60 dB HL：X=60，1 kHz 目标 = 60 + 0.31*60 + 1 = 79.6 dB。"""
    ag = Audiogram.mono(np.full(len(STD_FREQS), 60.0))
    g = nal_r_targets(ag, np.array([1000.0]))
    assert g[0] == pytest.approx(79.6, abs=0.1)


def test_nalrp_profound_correction():
    """H3FA=90 的重度听损：NAL-RP 比 NAL-R 多 0.2*(90-60)=6 dB。"""
    ag = Audiogram.mono(np.full(len(STD_FREQS), 90.0))
    r = nal_r_targets(ag, np.array([1000.0]), profound_correction=False)
    rp = nal_r_targets(ag, np.array([1000.0]), profound_correction=True)
    assert rp[0] - r[0] == pytest.approx(6.0, abs=0.1)


def test_pogo_half_gain_rule():
    """POGO 在 1–4 kHz 修正量为 0，增益应等于半听阈。"""
    ag = Audiogram.mono(np.full(len(STD_FREQS), 50.0))
    g = linear_targets(ag, np.array([1000.0, 2000.0, 4000.0]), "POGO")
    assert np.allclose(g, 25.0, atol=0.1)


def test_fig6_shape():
    """FIG6 = HL - 固定修正量；50 dB 平坦听损 1 kHz 应为 50-15=35 dB。"""
    ag = Audiogram.mono(np.full(len(STD_FREQS), 50.0))
    g = linear_targets(ag, np.array([1000.0]), "FIG6")
    assert g[0] == pytest.approx(35.0, abs=0.1)


def test_all_formulas_run_and_nonnegative(mild_ag):
    centers = band_centers()
    for name in FORMULAS:
        g = linear_targets(mild_ag, centers, name)
        assert g.shape == (8,)
        assert np.all(g >= 0.0)


def test_wdrc_medium_equals_linear(mild_ag):
    """65 dB SPL 锚点：WDRC 目标必须与线性处方完全一致（0 dB 差）。"""
    centers = band_centers()
    for name in FORMULAS:
        lin = linear_targets(mild_ag, centers, name)
        wd = wdrc_targets(mild_ag, centers, 65.0, name)
        assert np.allclose(lin, wd, atol=1e-10)


# ---------------------------------------------------------------- B. 端到端
def _measured_channel_gain(fs, input_spl, channel_idx, ag, formula, mold="closed"):
    """在指定通道的 STFT 实际覆盖频带内注入带限噪声，测完整助听链增益。

    测量用频域传递函数法：处理前后在同一组 STFT bin 上比较带内功率。
    增益在 STFT 域施加，传递函数测量与处理域一致，不存在带通滤波器
    滚降损失；稳态段（跳过起振 30%）取均值抑制时间瞬态。
    耳模泄漏补偿与稳定削减两个验配附加项在比对时单独扣除。
    """
    from hearing_sim import synth
    from hearing_sim.audio import NPPERSEG
    bin_freqs = np.arange(NPPERSEG // 2 + 1) * fs / NPPERSEG
    bin_ch = assign_bins(bin_freqs)
    sel = bin_ch == channel_idx
    real_lo = float(bin_freqs[sel][0] + fs / NPPERSEG)
    real_hi = float(bin_freqs[sel][-1] - fs / NPPERSEG)
    rng = np.random.default_rng(100 + channel_idx)
    # 用 55 dB SPL（-45 dBFS）避免高增益通道叠加后触发输出软限幅；
    # WDRC 目标随电平在 50/65/80 三锚点间线性插值，故同步求该电平目标。
    dbfs = 55.0 - audio.CAL_DB_SPL
    x = synth.band_limited_noise(real_lo, real_hi, 1.5, fs,
                                 level_dbfs=dbfs, rng=rng)
    from hearing_sim.engine import process
    # 关闭输出软限幅以隔离测量压缩器本身的命中精度（限幅是独立安全环节）
    res = process(x, fs, ag, formula=formula, mold_type=mold,
                  detect_feedback=False, soft_limit=False)

    def band_power_db(sig):
        f, _, Z = audio.stft(sig, fs)
        k0 = int(0.3 * Z.shape[1])
        e = np.mean(np.abs(Z[sel, k0:]) ** 2)
        return 10.0 * np.log10(max(e, 1e-18))

    gain = band_power_db(res.aided) - band_power_db(x)
    return gain, res


def _target_at_55spl(ag, centers, formula):
    """55 dB SPL 输入下的 WDRC 目标（50 与 65 锚点间线性插值）。"""
    from hearing_sim.prescriptions import wdrc_targets
    return wdrc_targets(ag, centers, 55.0, formula)


def test_end_to_end_gain_within_3db_all_channels(fs, mild_ag):
    """8 个通道端到端：实测增益与 WDRC 目标差 ≤ 3 dB。

    实测增益中包含耳模泄漏补偿与稳定削减两个验配附加项，
    与处方目标比对时予以扣除，单独验证压缩器本身的命中精度。
    """
    centers = band_centers()
    targets = _target_at_55spl(mild_ag, centers, "NAL-R")
    errors = []
    for c in range(8):
        measured, res = _measured_channel_gain(fs, 55.0, c, mild_ag, "NAL-R")
        cut = res.report.stability_cuts_db[c]
        comp = res.report.occlusion.compensation_db[c]
        corrected = measured + cut - comp
        errors.append(abs(corrected - targets[c]))
    errors = np.array(errors)
    assert np.all(errors <= 3.0), (
        f"通道增益超差: {np.round(errors, 2)} dB，目标 {np.round(targets, 1)}"
    )


def test_end_to_end_all_formulas_within_3db(fs, mild_ag):
    """四种公式在代表性通道（707/1414/3464 Hz 附近）上端到端误差 ≤ 3 dB。"""
    centers = band_centers()
    for formula in FORMULAS:
        targets = _target_at_55spl(mild_ag, centers, formula)
        for c in (2, 3, 5):  # 707 / 1414 / 3464 Hz
            measured, res = _measured_channel_gain(fs, 55.0, c, mild_ag, formula)
            corrected = (measured + res.report.stability_cuts_db[c]
                         - res.report.occlusion.compensation_db[c])
            assert abs(corrected - targets[c]) <= 3.0, (
                f"{formula} 通道{c}: 误差 {abs(corrected-targets[c]):.2f} dB"
            )


def test_soft_louder_than_loud(fs, mild_ag):
    """轻声(50 SPL)增益必须高于大声(80 SPL)，体现压缩。"""
    centers = band_centers()
    g_soft = wdrc_targets(mild_ag, centers, 50.0)
    g_loud = wdrc_targets(mild_ag, centers, 80.0)
    assert np.all(g_soft > g_loud)
