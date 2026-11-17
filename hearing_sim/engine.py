"""处理引擎：裸耳 / 助听两条完整链路 + 性能计时（验收指标 4）。

裸耳链路：STFT → 阈值门限 → 重振 → 频谱涂抹 → iSTFT
助听链路：STFT → 耳模泄漏补偿 → WDRC 压缩增益（含稳定余量保护）
        → iSTFT → 啸叫陷波抑制 → 软限幅
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from . import audio, channels as ch_mod, feedback as fb_mod, hearing_loss as hl_mod, occlusion as occ_mod
from . import wdrc
from .audiogram import Audiogram
from .channels import NUM_CHANNELS, assign_bins, band_centers


@dataclass
class FittingReport:
    """一次完整验配的全部中间量，供前端绘图与说明。"""

    formula: str
    mold_type: str
    channel_centers_hz: np.ndarray
    target_gains_db: np.ndarray          # 65 dB SPL 下每通道处方目标
    applied_gains_db: np.ndarray         # 实际每通道增益（含补偿/削减）
    occlusion: occ_mod.OcclusionResult
    stability_margin_db: np.ndarray
    stability_cuts_db: np.ndarray
    feedback: fb_mod.FeedbackResult | None = None
    processing_seconds: float = 0.0
    audio_duration_seconds: float = 0.0
    realtime_ratio: float = 0.0


@dataclass
class ProcessResult:
    unaided: np.ndarray
    aided: np.ndarray
    fs: int
    report: FittingReport
    extra: dict = field(default_factory=dict)


def process(x: np.ndarray, fs: int, ag: Audiogram,
            formula: str = "NAL-R", mold_type: str = "open",
            ear: str = "left", detect_feedback: bool = True,
            smearing: bool = True, soft_limit: bool = True) -> ProcessResult:
    """对一段音频同时生成裸耳与助听两个版本。

    soft_limit=False 时关闭输出 tanh 软限幅，用于纯压缩器精度测量
    （真实佩戴时限幅始终开启，保护残余听力）。
    """
    t0 = time.perf_counter()
    x = audio.to_mono(x)
    duration = len(x) / fs

    bin_freqs, _, Z = audio.stft(x, fs)
    centers = band_centers()
    hl_at_bins = ag.interp_hl(bin_freqs, ear)

    # 统一的时域带通 RMS 电平估计（两条链路共用，保证电平感知一致）；
    # 复用上面已算好的 STFT，避免长信号重复变换
    from .audio import HOP, NPPERSEG
    levels_spl = wdrc.time_domain_channel_levels(
        x, fs, ch_mod.BAND_EDGES, frame_len=NPPERSEG, hop=HOP,
        stft_Z=Z, stft_freqs=bin_freqs,
    )

    # ---------------- 裸耳链路 ----------------
    Z_loss = hl_mod.simulate_unaided(
        Z, bin_freqs, hl_at_bins, smearing=smearing, levels_spl=levels_spl
    )
    y_unaided = audio.istft(Z_loss, fs, length=len(x))

    # ---------------- 助听链路 ----------------
    occlusion = occ_mod.compute_occlusion(bin_freqs, mold_type)
    target_med = wdrc.wdrc_targets(ag, centers, 65.0, formula, ear)

    # 稳定余量保护（验配侧防啸）
    stable_gains, stab_cuts = fb_mod.auto_stabilize(target_med)
    margin = fb_mod.stability_margin(target_med)

    # 每通道净附加增益 = 泄漏补偿 - 稳定削减
    extra_db = occlusion.compensation_db - stab_cuts
    bin_gain, frame_gains = wdrc.wdrc_gains(
        ag, fs, np.abs(Z), bin_freqs,
        formula=formula, ear=ear, extra_gain_db=extra_db,
        levels_spl=levels_spl,
    )
    Z_aided = Z * bin_gain
    y_aided = audio.istft(Z_aided, fs, length=len(x))

    # 信号侧啸叫检测与陷波
    fb_result = fb_mod.FeedbackResult()
    if detect_feedback:
        y_aided, fb_result = fb_mod.suppress_feedback(y_aided, fs, Z_aided, bin_freqs)
    # 报告的「实际通道增益」反映压缩器/补偿/稳定保护的净结果；
    # 陷波只压制单个窄频点（Q=30），不代表整个通道增益变化，故不计入。
    applied = frame_gains.mean(axis=1)

    if soft_limit:
        y_aided = audio.peak_soft_limit(y_aided, ceiling_dbfs=-1.0)

    elapsed = time.perf_counter() - t0
    report = FittingReport(
        formula=formula,
        mold_type=mold_type,
        channel_centers_hz=centers,
        target_gains_db=target_med,
        applied_gains_db=applied,
        occlusion=occlusion,
        stability_margin_db=margin,
        stability_cuts_db=stab_cuts,
        feedback=fb_result,
        processing_seconds=elapsed,
        audio_duration_seconds=duration,
        realtime_ratio=duration / elapsed if elapsed > 0 else float("inf"),
    )
    return ProcessResult(
        unaided=y_unaided,
        aided=y_aided,
        fs=fs,
        report=report,
        extra={
            "bin_freqs": bin_freqs,
            "hl_at_bins": hl_at_bins,
            "frame_gains_db": frame_gains,
        },
    )


def benchmark(fs: int = 24000, duration_s: float = 60.0) -> dict:
    """性能自测：处理 60 秒音频的耗时与实时倍率。"""
    from .synth import speech_like_signal
    from .audiogram import Audiogram

    rng = np.random.default_rng(7)
    x = speech_like_signal(duration_s, fs, rng)
    ag = Audiogram.from_preset("中重度高频陡降")
    result = process(x, fs, ag)
    return {
        "duration_s": duration_s,
        "processing_seconds": result.report.processing_seconds,
        "realtime_ratio": result.report.realtime_ratio,
        "meets_2s_target": result.report.processing_seconds <= 2.0,
    }
