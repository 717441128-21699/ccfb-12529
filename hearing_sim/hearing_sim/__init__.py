"""助听器验配模拟系统 (Hearing Aid Fitting Simulator)

模块组成
--------
- audiogram:    听力图数据模型与对数频率插值
- prescription: 公开处方公式 (NAL-R / NAL-RP / WDRC 响度归一化)
- filterbank:   8 通道滤波器组 (时域 Linkwitz-Riley 与频域分带)
- compressor:   分通道宽动态范围压缩 (WDRC, 轻声/大声分开压缩)
- leakage:      耳模开放/封闭低频泄漏建模与自动补偿
- feedback:     啸叫频点检测与陷波抑制
- smearing:     Baer & Moore (1993) 频谱展宽 (言语清晰度下降模拟)
- loss_sim:     听力损失模拟 (阈值抬升 + 响度重振 + 频谱展宽)
- engine:       STFT 重叠相加处理引擎 (助听前 / 助听后两条通路)
- io_audio:     音频读写与重采样
- calibration:  耳机声学校准

本系统仅用于验配咨询与家属试听演示, 不能替代临床真耳分析 (REM) 与医学诊断。
"""

__version__ = "1.0.0"

ENGINE_FS = 32000  # 引擎统一采样率 Hz
