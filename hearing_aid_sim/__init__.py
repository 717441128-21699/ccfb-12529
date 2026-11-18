"""助听器验配模拟系统 —— 核心算法包。

模块划分
--------
- config:     全局常量（通道、频段、声校准）
- audiogram:  听力图数据模型与对数频率插值
- prescription: 公开处方公式 NAL-R / NAL-RP（主）与 POGO（对照）
- coupling:   耳模开放/封闭低频漏音模型与自动补偿
- wdrc:       轻声/大声分通道压缩（WDRC）
- feedback:   啸叫频点检测、陷波抑制、自适应反馈抵消（NLMS）
- loss_sim:   听损模拟（阈值衰减 + 响度重振 + 频谱涂抹致言语清晰度下降）
- engine:     STFT 八通道整机处理链
- audio_io:   音频读写与 dB SPL 校准
"""

from .audiogram import Audiogram
from .engine import HearingAidEngine, process_aided, process_unaided
from .prescription import nal_r, nal_rp, pogo, target_gain

__all__ = [
    "Audiogram",
    "HearingAidEngine",
    "process_aided",
    "process_unaided",
    "nal_r",
    "nal_rp",
    "pogo",
    "target_gain",
]
