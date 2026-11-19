"""分通道宽动态范围压缩 (WDRC)。

静态特性
--------
每个通道一条 dB 输入-输出折线 (目标增益表驱动), 折线之外为 1:1 线性。
折线点由 prescription.wdrc_gains / NAL-R 65 dB 目标 + 压缩比生成。
轻声 (40~50 dB SPL) 给高增益, 大声 (80+ dB SPL) 增益自动降低, 实现分开压缩。

动态特性
--------
RMS 包络检测, attack / release 一阶平滑:
    alpha = exp(-dt / tau)
输出经 OSPL90 (不舒适阈) 天花板限幅。
"""
from __future__ import annotations

import numpy as np

from .filterbank import N_CHANNELS


def build_static_curve(
    gain_table: np.ndarray | None,
    input_levels: np.ndarray | None,
    gains65: np.ndarray,
    compression_ratios: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """构造每个通道的静态 (input_dB, gain_dB) 折线。

    若提供非线性 gain_table (n_ch, n_level) 直接使用;
    否则以 65 dB 目标增益 + 压缩比生成线性 dB 折线 (线性公式)。
    返回 (inputs (n_level,), gains (n_ch, n_level))。
    """
    if gain_table is not None:
        return np.asarray(input_levels, float), np.asarray(gain_table, float)

    # 线性公式退化: 以 65 dB 为锚, CR 决定斜率 (gain 随输入变化)
    levels = np.array([40.0, 50.0, 65.0, 80.0, 90.0, 100.0])
    gains = np.zeros((N_CHANNELS, len(levels)))
    for k in range(N_CHANNELS):
        cr = max(compression_ratios[k], 1.0)
        # 输出斜率 = 1/CR, 增益斜率 = 1/CR - 1
        gains[k] = gains65[k] + (1.0 / cr - 1.0) * (levels - 65.0)
    return levels, gains


def _alpha(tau_ms: float, frame_ms: float) -> float:
    if tau_ms <= 0:
        return 0.0
    return float(np.exp(-frame_ms / tau_ms))


class WDRC:
    """逐通道 WDRC 压缩器 (作用于 STFT 帧幅度)。"""

    def __init__(
        self,
        input_levels: np.ndarray,
        gain_table: np.ndarray,
        ldl_spl: np.ndarray,
        fs: float,
        hop: int,
        attack_ms: float = 5.0,
        release_ms: float = 80.0,
        calibration_db_spl: float = 94.0,
        ref_rms: float = 1.0,
    ):
        self.input_levels = np.asarray(input_levels, float)
        self.gain_table = np.asarray(gain_table, float)
        self.ldl_spl = np.asarray(ldl_spl, float)
        self.fs = fs
        self.frame_ms = 1000.0 * hop / fs
        self.a_att = _alpha(attack_ms, self.frame_ms)
        self.a_rel = _alpha(release_ms, self.frame_ms)
        self.cal = calibration_db_spl
        self.ref_rms = ref_rms
        # 每通道包络状态 (dB SPL)
        self.env = np.full(N_CHANNELS, -10.0)
        self.gain_state = np.zeros(N_CHANNELS)

    def reset(self) -> None:
        self.env.fill(-10.0)
        self.gain_state.fill(0.0)

    def target_gain_db(self, input_db_spl: np.ndarray) -> np.ndarray:
        """查表 (线性插值, 表外平坦) 得到每通道目标增益。"""
        return np.array([
            np.interp(input_db_spl[k], self.input_levels, self.gain_table[k])
            for k in range(N_CHANNELS)
        ])

    def process_frame(self, band_rms: np.ndarray) -> np.ndarray:
        """输入每通道 RMS, 输出每通道线性增益 (向量化 attack/release)。"""
        rms = np.maximum(band_rms, 1e-8)
        input_db = 20.0 * np.log10(rms / self.ref_rms) + self.cal

        # 非对称包络: 上升用 attack, 下降用 release
        up = input_db > self.env
        a = np.where(up, self.a_att, self.a_rel)
        self.env = a * self.env + (1.0 - a) * input_db

        target = self.target_gain_db(self.env)
        # 增益平滑: 增益下降(压缩介入)要快 -> attack; 上升(恢复)要慢 -> release
        gain_down = target < self.gain_state
        ag = np.where(gain_down, self.a_att, self.a_rel)
        self.gain_state = ag * self.gain_state + (1.0 - ag) * target

        # OSPL90 天花板
        output_db = self.env + self.gain_state
        over = output_db - self.ldl_spl
        gain = self.gain_state - np.maximum(over, 0.0)
        return 10.0 ** (gain / 20.0)
