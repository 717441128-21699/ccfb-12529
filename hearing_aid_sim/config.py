"""全局常量与默认参数。

声校准约定
==========
系统内部全部以 dB SPL 计算。默认 0 dBFS（满量程正弦峰值）对应 100 dB SPL，
即 RMS 为 1.0 的信号 = 100 - 3.01 ≈ 97 dB SPL。该换算可由调用方按耳机
实际校准情况覆盖（HearingAidEngine(cal_db_spl=...)）。
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------- 频率定义
# 标准听力图频率（Hz）
AUDIOGRAM_FREQS = np.array(
    [125, 250, 500, 1000, 2000, 3000, 4000, 6000, 8000], dtype=float
)

# 八个通道：在 125–8000 Hz 间按对数等比划分 9 条边、8 个带
N_CHANNELS = 8
_F_LOW, _F_HIGH = 125.0, 8000.0
BAND_EDGES = _F_LOW * (_F_HIGH / _F_LOW) ** (np.arange(N_CHANNELS + 1) / N_CHANNELS)
BAND_EDGES[-1] = _F_HIGH  # 消除浮点误差
# 通道中心频率 = 相邻边的几何平均
CHANNEL_FREQS = np.sqrt(BAND_EDGES[:-1] * BAND_EDGES[1:])

# ---------------------------------------------------------------- STFT 参数
DEFAULT_SR = 44100
N_FFT = 1024          # 约 23 ms @44.1k
HOP = 256             # 75% 重叠，帧移约 5.8 ms
WINDOW = "hann"

#  WDRC 时间常数（秒）：快启动、慢释放
ATTACK_TAU = 0.005
RELEASE_TAU = 0.080

# ---------------------------------------------------------------- 声校准
# 0 dBFS（满量程正弦峰值）对应的 dB SPL。取 120 dB SPL 与专业助听器
# 测试系统（Fonix/Affinity 等，0 dBFS ≈ 118–120 dB SPL）一致，
# 保证 65 dB SPL 言语 + 最大 ~45 dB 处方增益后仍有数字裕量、不触发削波。
DEFAULT_CAL_DB_SPL = 120.0

# ---------------------------------------------------------------- 耦合预设
# vent 等效高通拐点（Hz），见 coupling.py 模型说明
COUPLING_PRESETS = {
    "closed": {"vent_corner_hz": 120.0, "slope_order": 1.0, "label": "封闭耳模"},
    "open":   {"vent_corner_hz": 700.0, "slope_order": 1.0, "label": "开放耳模"},
}
MAX_VENT_COMP_DB = 15.0       # 开放补偿物理上限（稳定裕量）
FEEDBACK_GUARD_DB = 6.0       # 啸叫频点附近允许的补偿削减

# ---------------------------------------------------------------- 响度不适
# LDL 近似模型（Skinner 1980 一类临床回归的简化形式，文档中注明为近似）：
# LDL = clip(100 + 0.35 * HL, 90, 115) dB SPL
LDL_SLOPE = 0.35
LDL_INTERCEPT = 100.0
LDL_MIN, LDL_MAX = 90.0, 115.0
LDL_RESERVE_DB = 3.0          # 输出限幅 = LDL - 3
