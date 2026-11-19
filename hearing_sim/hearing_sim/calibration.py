"""耳机声学校准。

本系统在内部以 0 dBFS = 94 dB SPL 为参考电平工作 (模拟测量麦克风 94 dB 校准惯例)。
家属试听前建议做一次耳机电平校准:
  1. 播放 1 kHz 校准音 (参考级, 65 dB SPL 目标);
  2. 用手机声级计或诊室 SPL 计在耳机耦合位置实测;
  3. 把差值作为 spl_offset 写入, 后续所有输出统一平移。
临床精确校准需耳模耦合腔 + 真耳分析仪, 本模块仅保证试听 A/B 两版
在同一电平基准下公平比较。
"""
from __future__ import annotations

import numpy as np

CAL_FREQ_HZ = 1000.0
CAL_TARGET_SPL = 65.0
REF_DB_SPL = 94.0  # 0 dBFS 对应 SPL


def calibration_tone(fs: int, duration_s: float = 2.0,
                     target_spl: float = CAL_TARGET_SPL) -> np.ndarray:
    """生成 1 kHz 校准音, 幅度对应 target_spl dB SPL。"""
    t = np.arange(int(fs * duration_s)) / fs
    amp = 10.0 ** ((target_spl - REF_DB_SPL) / 20.0)
    # 首尾 20 ms 淡入淡出, 避免咔哒声
    ramp = int(0.02 * fs)
    env = np.ones_like(t)
    env[:ramp] = np.linspace(0.0, 1.0, ramp)
    env[-ramp:] = np.linspace(1.0, 0.0, ramp)
    return (amp * env * np.sin(2.0 * np.pi * CAL_FREQ_HZ * t)).astype(np.float32)


def apply_spl_offset(x: np.ndarray, spl_offset_db: float) -> np.ndarray:
    """按校准差值整体平移电平 (线性限幅保护)。"""
    g = 10.0 ** (spl_offset_db / 20.0)
    y = x * g
    peak = np.max(np.abs(y)) if y.size else 0.0
    if peak > 0.99:
        y = y * (0.99 / peak)
    return y.astype(np.float32)
