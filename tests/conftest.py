"""pytest 公共装置。"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hearing_sim.audiogram import Audiogram  # noqa: E402
from hearing_sim import synth  # noqa: E402

FS = 24000


@pytest.fixture
def fs() -> int:
    return FS


@pytest.fixture
def mild_ag() -> Audiogram:
    return Audiogram.from_preset("轻度老年性聋(高频缓降)")


@pytest.fixture
def severe_ag() -> Audiogram:
    return Audiogram.from_preset("中重度高频陡降")


@pytest.fixture
def flat40_ag() -> Audiogram:
    # 平坦 40 dB HL，NAL-R 教材标准验证用例
    hl = np.full_like(Audiogram.STD_FREQS if hasattr(Audiogram, "STD_FREQS")
                      else np.arange(9), 40.0)
    from hearing_sim.audiogram import STD_FREQS
    return Audiogram.mono(np.full(len(STD_FREQS), 40.0))


@pytest.fixture
def speech_signal(fs):
    rng = np.random.default_rng(42)
    return synth.speech_like_signal(3.0, fs, rng)
