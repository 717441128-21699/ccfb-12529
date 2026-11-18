"""测试夹具：构造几种典型听力图与信号。"""

import numpy as np
import pytest

from hearing_aid_sim.audiogram import Audiogram
from hearing_aid_sim.audio_io import band_limited_noise, speech_shaped_noise
from hearing_aid_sim.config import (AUDIOGRAM_FREQS, BAND_EDGES,
                                    CHANNEL_FREQS, DEFAULT_SR)


@pytest.fixture
def sr():
    return DEFAULT_SR


@pytest.fixture
def normal_ag():
    return Audiogram.standard(np.zeros(9), ear="right")


@pytest.fixture
def flat_mild_ag():
    # 平坦型轻度 35 dB HL
    return Audiogram.standard(np.full(9, 35.0))


@pytest.fixture
def sloping_ag():
    # 高频下降型（老人最常见）：25 -> 70 dB HL
    return Audiogram.standard(np.array([25, 25, 30, 35, 45, 55, 60, 65, 70],
                                       dtype=float))


@pytest.fixture
def severe_ag():
    return Audiogram.standard(np.array([55, 55, 60, 65, 70, 75, 78, 80, 82],
                                       dtype=float))


@pytest.fixture
def speech_65(sr):
    """言语谱形噪声（动态测试用）。"""
    rng = np.random.default_rng(7)
    return speech_shaped_noise(sr * 2, sr, 65.0, rng)


@pytest.fixture
def steady_65(sr):
    """ANSI S3.22 式分带噪声：每个通道独立等电平带通噪声，
    用于处方目标符合度的稳态测量（带内能量均匀、无跨带窗泄漏）。"""
    rng = np.random.default_rng(8)
    return band_limited_noise(BAND_EDGES, sr * 2, sr, 65.0, rng)
