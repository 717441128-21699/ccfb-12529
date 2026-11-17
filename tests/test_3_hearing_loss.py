"""验收指标 3：裸耳听损模拟——不只是变小，言语清晰度也要下降。

三类机制各自验证：
1. 阈值门限：低于听阈的成分消失；
2. 响度重振：听阈附近衰减大、高电平等响（小声听不到、大声不嫌小）；
3. 频谱涂抹：谱峰对比度下降，相邻频率被展宽混叠。
"""
import numpy as np

from hearing_sim import audio, hearing_loss as hl_mod
from hearing_sim.audiogram import STD_FREQS, Audiogram
from hearing_sim.synth import multi_tone, pure_tone, speech_like_signal


def _loss_of_tone(fs, freq_hz, level_spl, hl_db_at_freq):
    """给一个正弦，返回裸耳模拟前后的电平差（dB）。

    走引擎统一的时域带通电平估计路径；纯音信号关闭频谱涂抹
    （涂抹模拟的是宽带言语中相邻谱峰的混叠，单频音无峰可混）。
    """
    from hearing_sim import wdrc
    from hearing_sim.audio import HOP, NPPERSEG
    from hearing_sim.channels import BAND_EDGES
    x = pure_tone(freq_hz, 1.5, fs, level_dbfs=level_spl - audio.CAL_DB_SPL)
    f, _, Z = audio.stft(x, fs)
    hl_bins = np.full_like(f, hl_db_at_freq)
    levels = wdrc.time_domain_channel_levels(x, fs, BAND_EDGES, NPPERSEG, HOP)
    Z2 = hl_mod.simulate_unaided(Z, f, hl_bins, smearing=False,
                                 levels_spl=levels)
    y = audio.istft(Z2, fs, length=len(x))
    # 稳态段测量，跳过两端起振/边界帧
    s = int(0.3 * fs)
    return audio.rms_dbfs(y[s:]) - audio.rms_dbfs(x[s:])


def test_inaudible_below_threshold(fs):
    """低于听阈 10 dB 的声音必须被门限静默（衰减 > 60 dB）。"""
    loss = _loss_of_tone(fs, 2000.0, level_spl=50.0, hl_db_at_freq=60.0)
    assert loss < -60.0


def test_above_threshold_audible(fs):
    """高于听阈 38 dB 的声音可闻且衰减有限（模型理论值 -9.8 dB，容差 3 dB）。"""
    loss = _loss_of_tone(fs, 2000.0, level_spl=98.0, hl_db_at_freq=60.0)
    assert -13.0 < loss < -6.0


def test_inaudible_well_below_threshold(fs):
    """远低于听阈的声音必须深度静默（补充用例：门限机制的正向验证）。"""
    loss = _loss_of_tone(fs, 2000.0, level_spl=40.0, hl_db_at_freq=70.0)
    assert loss < -60.0


def test_recruitment_steep_growth_near_threshold(fs):
    """重振核心特征：听阈附近响度增长异常陡峭。

    输入 65→75 dB SPL（+10 dB，HL=60，距听阈仅 5–15 dB），
    受损耳感知到的响度变化必须明显大于 10 dB（正常耳只感知 +10 dB）。
    """
    hl = 60.0
    loss_65 = _loss_of_tone(fs, 2000.0, 65.0, hl)
    loss_75 = _loss_of_tone(fs, 2000.0, 75.0, hl)
    perceived_change = 10.0 + (loss_75 - loss_65)
    assert perceived_change > 12.0, (
        f"听阈附近响度增长不够陡，感知变化仅 {perceived_change:.1f} dB"
    )


def test_recruitment_loud_approaches_normal(fs):
    """高电平时受损耳增益趋近 0（98 SPL、HL=50 理论 -2.2 dB，含门限边界容差）。"""
    loss = _loss_of_tone(fs, 1000.0, 98.0, 50.0)
    assert -9.0 < loss < 0.0


def test_recruitment_gain_monotonic_with_level(fs):
    """输入电平越高，重振衰减越小（增益单调回升到 0）。"""
    losses = [_loss_of_tone(fs, 2000.0, spl, 60.0)
              for spl in (65.0, 75.0, 85.0, 95.0)]
    assert all(b > a for a, b in zip(losses, losses[1:]))


def test_spectral_smearing_reduces_peak_contrast():
    """频谱涂抹后，窄峰相对邻域的对比度必须下降。"""
    fs = 24000
    rng = np.random.default_rng(1)
    # 两个靠近的强峰 + 弱背景
    x = multi_tone([1800.0, 2200.0], 0.5, fs, level_dbfs=-20.0)
    x += 0.02 * rng.standard_normal(len(x))
    f, _, Z = audio.stft(x, fs)
    f_safe = np.maximum(f, STD_FREQS[0])  # 0 Hz bin 不能取对数
    hl = np.interp(np.log2(f_safe), np.log2(STD_FREQS),
                   np.array([20, 25, 35, 45, 60, 70, 78, 85, 90], dtype=float))

    def contrast(mag):
        peak = mag.max(axis=0).mean()
        floor = np.median(mag, axis=0).mean()
        return 20 * np.log10(peak / max(floor, 1e-12))

    c_before = contrast(np.abs(Z))
    smeared = hl_mod.spectral_smear(np.abs(Z), f, hl)
    c_after = contrast(smeared)
    assert c_after < c_before - 3.0, f"谱峰对比度仅下降 {c_before - c_after:.1f} dB"


def test_smearing_blends_adjacent_peaks():
    """涂抹后两个相邻峰之间的谷被填高（频率选择性丧失的直接证据）。"""
    fs = 24000
    x = multi_tone([1800.0, 2400.0], 0.5, fs, level_dbfs=-20.0)
    f, _, Z = audio.stft(x, fs)
    hl = np.full_like(f, 70.0)
    mag0 = np.abs(Z).mean(axis=1)
    mag1 = hl_mod.spectral_smear(np.abs(Z), f, hl).mean(axis=1)
    valley = (f > 1950) & (f < 2250)
    assert mag1[valley].mean() > mag0[valley].mean() * 1.5


def test_unaided_speech_high_freqs_more_degraded(fs, severe_ag):
    """陡降型听损：高频言语成分的损伤应明显重于低频。"""
    rng = np.random.default_rng(3)
    x = speech_like_signal(2.0, fs, rng)
    f, _, Z = audio.stft(x, fs)
    hl_bins = severe_ag.interp_hl(f)
    Z2 = hl_mod.simulate_unaided(Z, f, hl_bins)
    mag0, mag1 = np.abs(Z), np.abs(Z2)
    low = (f >= 250) & (f <= 500)
    high = (f >= 3000) & (f <= 6000)
    loss_low = 20 * np.log10(mag1[low].mean() / max(mag0[low].mean(), 1e-12))
    loss_high = 20 * np.log10(mag1[high].mean() / max(mag0[high].mean(), 1e-12))
    assert loss_high < loss_low - 6.0


def test_erb_math():
    """ERB 正反变换自洽。"""
    f = np.array([250.0, 1000.0, 4000.0])
    back = hl_mod.erb_to_hz(hl_mod.hz_to_erb(f))
    assert np.allclose(f, back, rtol=1e-10)
