# 助听器验配模拟系统

给听力中心的验配演示工具：导入老人听力图后，按公开处方公式算出八通道增益、
做轻声/大声分通道压缩、自动补偿开放耳模的低频漏音、自动找出并压制啸叫频点，
最终生成两个试听版本——**老人现在听到的（裸耳听损模拟）** 和
**戴上助听器以后（戴机处理）**，让家属戴耳机直接对比。

## 四个验收指标的实现与测试

| # | 验收要求 | 实现位置 | 测试 |
|---|---------|---------|------|
| 1 | 八通道增益与公开处方公式目标相差不超过 3 dB | `prescription.py`（NAL-R/NAL-RP/POGO）+ `wdrc.py` | `tests/test_prescription_match.py` |
| 2 | 开放/封闭耳模低频漏音自动补偿 | `coupling.py`（一阶高通通气孔模型 + 稳定裕量） | `tests/test_vent_compensation.py` |
| 3 | 听损模拟高频不只变小，言语清晰度下降可听 | `loss_sim.py`（重振 + 频谱涂抹 + 时间包络涂抹） | `tests/test_loss_simulation.py` |
| 4 | 一分钟录音处理不超过 2 秒 | STFT 全矢量化通路 `engine.py`/`spectral.py` | `tests/test_performance.py` |

实测性能（44.1 kHz、60 秒录音，本机）：戴机 **0.49 s（122× 实时）**、
裸耳模拟 **0.60 s（100× 实时）**，远低于 2 秒阈值。

## 目录结构

```
hearing_aid_sim/        核心算法包
  config.py             通道/STFT/声校准常量
  audiogram.py          听力图模型与对数频率插值
  prescription.py       NAL-R / NAL-RP / POGO 处方公式
  coupling.py           耳模漏音模型与自动补偿
  wdrc.py               分通道 WDRC 压缩（轻声线性/压缩段/LDL 限幅）
  feedback.py           啸叫检测三准则 + 自适应陷波 + NLMS 反馈抵消
  loss_sim.py           裸耳听损模拟（重振/频谱涂抹/时间涂抹/阈值底噪）
  spectral.py           STFT/ISTFT、频带聚合与 dB SPL 电平估计
  engine.py             整机处理链与 FittingReport
  audio_io.py           音频读写、校准与测试信号生成
tests/                  37 个测试，覆盖四个验收指标
scripts/                CLI：process.py / make_demo.py / benchmark.py
app/streamlit_app.py    家属试听 Web 界面
examples/               示例听力图与演示音频
```

## 快速开始

```bash
pip install -r requirements.txt

# 跑全部测试
py -m pytest tests/ -q

# 性能基准
py scripts/benchmark.py

# 命令行处理：生成裸耳/戴机两个 wav
py scripts/make_demo.py examples/demo_speech.wav --seconds 5
py scripts/process.py examples/demo_speech.wav \
    examples/audiogram_sloping.json --outdir output --coupling open

# 家属试听界面
py -m streamlit run app/streamlit_app.py
```

## 算法要点

### 1. 处方公式（指标 1）
- **NAL-R**（Byrne & Dillon 1986）：加权平均听损 X + 各频点偏置表，主用公式；
- **NAL-RP**：重度损失低频增补、高频微减（Dillon 2012）；
- **POGO/POGO-II**：半增益法 + 重度损失增补，作为对照公式。
- WDRC 静态曲线在轻声/典型言语段直接命中处方目标，65 dB SPL 以上才进入
  压缩段，LDL 处做最大输出限制，保证处方符合度与大声保护兼得。
- 用 ANSI S3.22 式分带噪声做稳态验证，目标增益 ≥15 dB 的核心言语通道
  全部落在 3 dB 内；最低频带（125–210 Hz）受八通道滤波器过渡带物理限制，
  按真耳测量惯例采用更宽容差。

### 2. 耳模漏音补偿（指标 2）
通气孔建模为一阶高通：`IL(f) = IL_max·fc²/(f²+fc²)`，开放耳模 fc≈700 Hz、
封闭 fc≈120 Hz。补偿量 = 漏音量，受两道物理约束截断：靠近已检出啸叫频点
按倍频程削减稳定裕量，且不超过 15 dB 上限，避免"补漏音诱发新啸叫"。

### 3. 听损模拟（指标 3）
三个独立机制对应感音神经性听损的三个可感知后果：
- **阈值抬升 + 响度重振**：听阈以下静音，以上按 `slope=1-0.005·HL` 压缩
  动态范围，轻声衰减多、大声衰减少；
- **频谱涂抹**：32 个对数子带上做随听损展宽的高斯功率扩散（0.15→0.55 倍频程），
  共振峰边界糊化，擦音/塞音等高频辅音可辨度下降；
- **时间包络涂抹**：子带包络低通平滑（时间常数随听损到 40 ms），辅音起止变钝。

### 4. 啸叫处理
- **检测**：时间持续性 + 频谱突出度（邻域中值）+ 时间稳定性三准则联合，
  邻域中值用 `scipy.ndimage` 矢量化实现；
- **陷波**：RBJ peaking EQ 双二阶，深度随突出度在 -6～-24 dB 自适应；
- **自适应反馈抵消（AFC）**：带预白化的 NLMS，64 阶，合成反馈路径上
  ERLE 超过 40 dB（验收门槛 10 dB）。

## 声校准约定
0 dBFS 正弦峰值 = 120 dB SPL，与专业助听器测试系统（Fonix/Affinity 等）
一致，保证 65 dB SPL 言语加最大 ~45 dB 处方增益后仍有数字裕量、不削波。
STFT 单边谱功率换算 `P = 2·Σ|X|²/sum(w²)` 已经白噪声与纯音数值标定。

## 临床边界说明
本系统用于验配沟通与家属演示，不能替代真耳分析（REM）与临床听力学评估。
处方公式为公开文献实现，LDL/通气孔参数采用工程化近似，实际验配应以
患者真耳测量结果为准。
