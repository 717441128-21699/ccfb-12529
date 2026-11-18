"""验收指标 3：听损模拟不只让高频变小，言语清晰度下降也要听得出来。"""

import numpy as np

from hearing_aid_sim.config import CHANNEL_FREQS
from hearing_aid_sim.loss_sim import RETSPL_DB, perceived_level, recruitment_slope
from hearing_aid_sim.engine import HearingAidEngine


def _band_rms_db(x, sr):
    from hearing_aid_sim.spectral import stft, band_membership, band_levels_db_spl
    from hearing_aid_sim.config import BAND_EDGES
    spec, freqs, _ = stft(x, sr)
    m = band_membership(freqs, BAND_EDGES)
    return band_levels_db_spl(spec, m, 100.0).mean(axis=0)


def test_normal_hearing_preserved(normal_ag, speech_65, sr):
    """正常听力图：模拟输出与输入差异应很小（不应人为制造失真）。"""
    eng = HearingAidEngine(normal_ag, sr=sr)
    y = eng.process_unaided(speech_65)
    in_lvl = _band_rms_db(speech_65, sr)
    out_lvl = _band_rms_db(y, sr)
    assert np.all(np.abs(out_lvl - in_lvl) < 4.0)


def test_high_frequencies_are_attenuated(sloping_ag, speech_65, sr):
    """高频下降听损：输出高频电平明显低于低频。"""
    eng = HearingAidEngine(sloping_ag, sr=sr)
    y = eng.process_unaided(speech_65)
    out_lvl = _band_rms_db(y, sr)
    in_lvl = _band_rms_db(speech_65, sr)
    loss = in_lvl - out_lvl
    # 高频通道（4k 以上）衰减显著大于低频通道
    assert np.mean(loss[-2:]) > np.mean(loss[:2]) + 8.0


def test_spectral_smearing_reduces_formant_contrast(sloping_ag, sr):
    """频谱涂抹：窄带共振峰结构的峰谷对比度被抹平（清晰度机制之一）。"""
    # 构造带两个窄共振峰的谐波信号（模拟元音共振峰）
    t = np.arange(sr) / sr
    f0 = 150.0
    x = np.zeros_like(t)
    for h in range(1, 40):
        f = h * f0
        # 在 750Hz、2500Hz 放两个强共振峰
        boost = 1.0 + 9.0 * (
            np.exp(-((np.log2(f / 750.0)) / 0.12) ** 2)
            + np.exp(-((np.log2(f / 2500.0)) / 0.12) ** 2)
        )
        x += boost * np.sin(2 * np.pi * f * t) / h
    x /= np.max(np.abs(x))

    def contrast(sig):
        spec = np.abs(np.fft.rfft(sig * np.hanning(len(sig))))
        freqs = np.fft.rfftfreq(len(sig), 1 / sr)
        # 2500 Hz 共振峰峰值 vs 邻域谷底
        band = (freqs > 1800) & (freqs < 3200)
        return 10 * np.log10(np.max(spec[band]) / (np.median(spec[band]) + 1e-12))

    eng = HearingAidEngine(sloping_ag, sr=sr)
    y = eng.process_unaided(x)
    assert contrast(y) < contrast(x) - 3.0, (
        f"共振峰对比度未被抹平：{contrast(x):.1f} -> {contrast(y):.1f}")


def test_temporal_smearing_blunts_onset(sloping_ag, sr):
    """时间涂抹：短促辅音式脉冲的 onset 锐度下降（清晰度机制之二）。"""
    # 10 个 20 ms 短脉冲（模拟塞音 burst）
    x = np.zeros(sr)
    for k in range(10):
        start = int(k * 0.09 * sr)
        burst = np.random.default_rng(k).standard_normal(int(0.02 * sr))
        x[start:start + len(burst)] = burst * np.hanning(len(burst))

    def onset_sharpness(sig):
        env = np.abs(sig)
        diff = np.diff(env)
        return float(np.percentile(diff, 99))      # 包络最陡上升沿

    eng = HearingAidEngine(sloping_ag, sr=sr)
    y = eng.process_unaided(x)
    assert onset_sharpness(y) < onset_sharpness(x) * 0.8


def test_recruitment_loud_sounds_not_reduced_like_soft(sloping_ag, sr):
    """重振：同一频带内，轻声衰减比例大于大声（动态范围收窄）。"""
    from hearing_aid_sim.loss_sim import recruitment_slope
    # 取 2 kHz 频带（HL=45，阈值 49 dB SPL，slope<1）
    hl = 45.0
    thr = hl + RETSPL_DB
    slope = recruitment_slope(np.array([hl]))[0]
    soft_l, loud_l = 55.0, 85.0           # 都在听阈以上
    g_soft = -(1 - slope) * (soft_l - thr)
    g_loud = -(1 - slope) * (loud_l - thr)
    # 轻声的衰减量（绝对值）小于大声的绝对衰减，但相对压缩比体现重振：
    # 关键验证——输出动态范围 < 输入动态范围
    out_soft = soft_l + g_soft
    out_loud = loud_l + g_loud
    assert (out_loud - out_soft) < (loud_l - soft_l)
    assert g_soft <= 0 and g_loud <= 0   # 全程纯衰减


def test_inaudible_below_threshold(sloping_ag, sr):
    """听阈以下的信号在目标频带应被静音（带通测量，排除其他频带干扰）。"""
    from hearing_aid_sim.audio_io import pure_tone
    from scipy import signal as sig
    # 4 kHz 听阈约 64 dB SPL；给 50 dB SPL（明确低于阈值、又高于数字底噪）
    x = pure_tone(4000.0, sr, 50.0)
    eng = HearingAidEngine(sloping_ag, sr=sr)
    y = eng.process_unaided(x, rng=np.random.default_rng(1))
    # 只测 3.5–4.5 kHz 频带
    sos = sig.butter(4, [3500 / (sr / 2), 4500 / (sr / 2)],
                     btype="band", output="sos")
    in_band = np.sqrt(np.mean(sig.sosfilt(sos, x) ** 2))
    out_band = np.sqrt(np.mean(sig.sosfilt(sos, y) ** 2))
    in_db = 20 * np.log10(in_band + 1e-12)
    out_db = 20 * np.log10(out_band + 1e-12)
    assert out_db < in_db - 15.0


def test_recruitment_slope_monotonic():
    hl = np.array([0, 30, 60, 90])
    s = recruitment_slope(hl)
    assert np.all(np.diff(s) <= 0) and s[-1] >= 0.55
    # 听阈以下返回值低于该耳听阈坐标（标记不可闻）
    p_quiet = perceived_level(np.array([20.0]), np.array([60.0]))
    assert p_quiet[0] < 60.0 + RETSPL_DB
    # 重振核心性质：听损耳的响度曲线斜率（dP/dL = 1/slope）随听损增大，
    # 即同样增加 10 dB 输入，重听耳内部响度跳得更多
    slopes = 1.0 / recruitment_slope(np.array([10.0, 40.0, 70.0]))
    assert np.all(np.diff(slopes) > 0)


def test_perceived_level_above_threshold_grows():
    """可闻区内，输入越大内部响度越大，且听阈处连续。"""
    hl = np.array([40.0])
    levels = np.array([50.0, 70.0, 90.0])
    p = perceived_level(levels, hl)
    assert np.all(np.diff(p) > 0)
