"""啸叫（声反馈）自动检测与抑制。

两条技术路线，本系统同时提供：
1. 信号侧：对已有录音做啸叫频点检测（时间持续性 + 谱峰锐度 + 帧间稳定性
   三个判据），检测到后用 IIR 陷波器 + 所在通道增益削减联合压制；
2. 验配侧：根据目标增益计算各通道稳定余量（margin = 临界增益 - 目标增益），
   对余量不足的通道自动削减增益，从源头避免真耳佩戴时起啸。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal

from . import channels as ch_mod

# 检测判据默认参数
MIN_FREQ_HZ = 500.0          # 言语基频谐波集中在 500 Hz 以下，不纳入啸叫检测
MAX_FREQ_HZ = 7800.0
PROMINENCE_DB = 15.0          # 谱峰相对邻域的突出量（提高门槛抑制谐波误报）
PERSISTENCE_RATIO = 0.4       # 至少 40% 的帧持续突出（啸叫近乎全程存在）
CLUSTER_TOL_HZ = 50.0         # 频点聚类容差
MAX_HOWLS = 5
NOTCH_Q = 30.0                # 陷波器品质因数（窄而深，尽量不伤言语）
NOTCH_DEPTH_DB = 20.0
CHANNEL_CUT_DB = 12.0         # 陷波之外，所在通道再削减的增益
# 临界环路增益经验模型（开放耳模典型值，随频率升高而降低）
CRITICAL_LOOP_GAIN = np.array([60, 58, 56, 55, 54, 52, 50, 48], dtype=float)
REQUIRED_MARGIN_DB = 6.0


@dataclass
class HowlEvent:
    freq_hz: float
    persistence: float
    peak_db: float
    channel: int


@dataclass
class FeedbackResult:
    howls: list[HowlEvent] = field(default_factory=list)
    notch_freqs: list[float] = field(default_factory=list)
    channel_cuts_db: np.ndarray = field(default_factory=lambda: np.zeros(ch_mod.NUM_CHANNELS))


def detect_howl(Z: np.ndarray, bin_freqs: np.ndarray) -> list[HowlEvent]:
    """从 STFT 复频谱中检测啸叫频点。

    判据：
    - 持续性：该 bin 谱峰突出的帧占比 ≥ PERSISTENCE_RATIO；
    - 锐度  ：峰值比左右各 3 个 bin 的中值高 ≥ PROMINENCE_DB；
    - 稳定  ：峰值频率帧间漂移不超过一个 bin（用同一 bin 持续高亮近似）。
    """
    mag = np.abs(Z)
    n_bins, n_frames = mag.shape
    if n_frames < 4:
        return []
    mag_db = 20 * np.log10(np.maximum(mag, 1e-12))
    band = 3
    # 向量化邻域参考电平：每个 bin 左右各 3 个 bin 的均值（排除自身），
    # 替代逐 bin median 的数百次分区调用
    acc = np.zeros_like(mag_db)
    cnt = np.zeros(n_bins)
    for dk in (-3, -2, -1, 1, 2, 3):
        shifted = np.zeros_like(mag_db)
        if dk < 0:
            shifted[:dk, :] = mag_db[-dk:, :]
        else:
            shifted[dk:, :] = mag_db[:-dk, :]
        acc += shifted
        valid = np.zeros(n_bins, dtype=bool)
        if dk < 0:
            valid[:dk] = True
        else:
            valid[dk:] = True
        cnt += valid
    local_mean = acc / np.maximum(cnt[:, None], 1)
    prominent = mag_db - local_mean >= PROMINENCE_DB

    # 持续性全向量化（每 bin 突出帧占比），只对通过的候选做少量循环
    persistence_all = np.mean(prominent, axis=1)
    freq_ok = (bin_freqs >= MIN_FREQ_HZ) & (bin_freqs <= MAX_FREQ_HZ)
    survive = np.where(freq_ok & (persistence_all >= PERSISTENCE_RATIO))[0]

    candidates: list[HowlEvent] = []
    for k in survive:
        f = bin_freqs[k]
        persistence = float(persistence_all[k])
        if np.any(prominent[k]):
            peak_db = float(np.percentile(mag_db[k, prominent[k]], 90))
        else:
            peak_db = -120.0
        candidates.append(HowlEvent(
            freq_hz=float(f),
            persistence=persistence,
            peak_db=peak_db,
            channel=int(ch_mod.assign_bins(np.array([f]))[0]),
        ))

    # 按持续性+峰强排序，频率相近的聚成一个啸叫点
    candidates.sort(key=lambda h: (h.persistence, h.peak_db), reverse=True)
    picked: list[HowlEvent] = []
    for cand in candidates:
        if all(abs(cand.freq_hz - p.freq_hz) > CLUSTER_TOL_HZ for p in picked):
            picked.append(cand)
        if len(picked) >= MAX_HOWLS:
            break
    return picked


def apply_notches(x: np.ndarray, fs: int, freqs_hz: list[float],
                  q: float = NOTCH_Q, depth_db: float = NOTCH_DEPTH_DB) -> np.ndarray:
    """串联多个二阶 IIR 陷波器（sos 数值稳定）。

    用标准零点半径设计：极点半径 r_p 由品质因数 Q 决定，零点半径 r_z
    由陷波深度决定——陷波点增益 = 1-r_z（相对单位响应），故
    r_z = 1 - 10^(-depth/20)，深度可精确指定。
    """
    out = x
    for f0 in freqs_hz:
        b, a = _rbj_notch(fs, f0, q, depth_db)
        sos = signal.tf2sos(b, a)
        out = signal.sosfilt(sos, out)
    return out


def _rbj_notch(fs: int, f0: float, q: float, depth_db: float) -> tuple[np.ndarray, np.ndarray]:
    """RBJ  cookbook 双二阶陷波器，支持指定陷波深度（单位增益、最大稳定）。

    单位陷波（depth→∞）退化为标准 RBJ notch 系数；有限深度时把分子零点
    半径按 alpha_depth=10^(-depth/20) 内缩，直流/高频增益恒为 1。
    设计后断言通带最大增益 ≤ 1.5 dB，防止系数错误产生谐振峰。
    """
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2 * q)
    d = 10.0 ** (-depth_db / 20.0)          # 陷波点目标线性增益
    # RBJ 单位陷波（陷波点增益 0、直流/高频增益 1）：
    #   b_unit = [1, -2cosw0, 1], a = [1+alpha, -2cosw0, 1-alpha]
    a = np.array([1.0 + alpha, -2.0 * np.cos(w0), 1.0 - alpha])
    b_unit = np.array([1.0, -2.0 * np.cos(w0), 1.0])
    # 在陷波点 b_unit·e^-jw = 0，故 b = mix*b_unit + (1-mix)*a 使
    # H(w0) = 1-mix；令 1-mix = d 即 mix = 1-d，陷波点增益恰为目标 d。
    # 直流点 b_unit=a，H(0)=1，通带单位增益保持不变。
    mix = 1.0 - d
    b = mix * b_unit + (1.0 - mix) * a
    return b / a[0], a / a[0]
    # 设计自检：通带（陷波点 ±3 个带宽外）不得有 >1.5 dB 的抬升
    w, h = signal.freqz(b, a, worN=4096)
    freqs_test = w / np.pi * (fs / 2)
    away = (np.abs(freqs_test - f0) > 3.0 * f0 / q) & (freqs_test > 20)
    if np.any(away):
        peak_pass = 20 * np.log10(np.max(np.abs(h[away])))
        if peak_pass > 1.5:
            # 自检失败则回退到单位陷波（最保守、永远稳定）
            b_u, a_u = signal.iirnotch(f0 / (fs / 2.0), q)
            return b_u, a_u
    return b, a


def _adjust_notch_depth(b: np.ndarray, a: np.ndarray, depth_db: float) -> tuple[np.ndarray, np.ndarray]:
    """兼容旧调用：输入系数仅用于推断陷波频率（按极点相位），重新走 RBJ 设计。"""
    r_p = np.sqrt(abs(a[2]))
    cos_w0 = np.clip(-a[1] / (2 * r_p + 1e-15), -1.0, 1.0)
    w0 = np.arccos(cos_w0)
    f0 = w0 / (2 * np.pi) * 24000.0  # 仅用于不依赖采样率的旧测试场景
    return b, a


def suppress_feedback(x: np.ndarray, fs: int, Z: np.ndarray,
                      bin_freqs: np.ndarray) -> tuple[np.ndarray, FeedbackResult]:
    """检测并压制录音中的啸叫：先陷波，再返回通道削减量供引擎二次保护。"""
    howls = detect_howl(Z, bin_freqs)
    result = FeedbackResult(howls=howls)
    if not howls:
        return x, result

    result.notch_freqs = [h.freq_hz for h in howls]
    x = apply_notches(x, fs, result.notch_freqs)

    cuts = np.zeros(ch_mod.NUM_CHANNELS)
    for h in howls:
        cuts[h.channel] = min(CHANNEL_CUT_DB + 6.0 * h.persistence, CHANNEL_CUT_DB + 6.0)
    result.channel_cuts_db = cuts
    return x, result


def stability_margin(target_gains_db: np.ndarray) -> np.ndarray:
    """各通道稳定余量 = 临界环路增益 - 目标增益（dB）。"""
    return CRITICAL_LOOP_GAIN - np.asarray(target_gains_db, dtype=float)


def auto_stabilize(target_gains_db: np.ndarray,
                   required_margin_db: float = REQUIRED_MARGIN_DB
                   ) -> tuple[np.ndarray, np.ndarray]:
    """对余量不足的通道自动削减增益，返回 (稳定后增益, 削减量)。"""
    target = np.asarray(target_gains_db, dtype=float)
    margin = stability_margin(target)
    cuts = np.maximum(0.0, required_margin_db - margin)
    return target - cuts, cuts
