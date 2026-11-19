"""pytest 公共夹具: 确保从项目根导入包、提供固定随机种子。"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def rng():
    return np.random.default_rng(2024)
