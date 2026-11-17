"""助听器验配模拟系统 DSP 核心包。

模块划分
--------
- audio:         音频 I/O、STFT/iSTFT、电平校准
- audiogram:     听力图数据结构、插值、常见预设
- channels:      8 通道分频带定义
- prescriptions: NAL-R / NAL-RP / POGO / FIG6 公开处方公式与非线性目标
- wdrc:          轻声/大声分开的宽动态范围压缩
- occlusion:     耳模气孔泄漏与低频自动补偿
- feedback:      啸叫频点自动检测与抑制（陷波 + 通道增益削减 + 稳定余量分析）
- hearing_loss:  裸耳听损模拟（阈值门限 + 响度重振 + 频谱涂抹）
- engine:        助听/裸耳两条完整处理链与性能计时
- synth:         测试信号合成
"""

__all__ = [
    "audio",
    "audiogram",
    "channels",
    "prescriptions",
    "wdrc",
    "occlusion",
    "feedback",
    "hearing_loss",
    "engine",
    "synth",
]

__version__ = "1.0.0"
