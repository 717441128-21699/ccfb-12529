# 助听器验配模拟系统 (Hearing Aid Fitting Simulator)

给听力中心用的验配可视化与家属试听工具。导入老人听力图后，按公开处方公式计算
**8 个通道**各自的增益，对轻声/大声分开做宽动态范围压缩 (WDRC)，自动补偿开放/封闭
耳模的低频泄漏，自动找出并压制啸叫频点；最终生成两个版本的音频供家属戴耳机 A/B 试听：

- **助听前**：老人现在实际听到的声音（听阈抬升 + 响度重振 + 高频频谱展宽导致的清晰度下降）
- **助听后**：戴上助听器后听到的声音（8 通道 WDRC + 泄漏补偿 + 啸叫抑制）

> 本系统用于验配咨询、家属沟通和教学演示，**不能替代临床真耳分析 (REM) 与医学诊断**。

---

## 四项硬指标的达成情况

| # | 需求 | 实现方式 | 验收测试 | 实测结果 |
|---|------|----------|----------|----------|
| 1 | 8 通道增益与公开处方公式目标相差 ≤3 dB | NAL-R / NAL-RP 原始方程 + WDRC 响度归一化目标表，引擎按 Parseval 校准的分带电平查表施加增益 | `tests/test_1_prescription.py` | 8 通道误差 **≤0.9 dB**（OSPL90 触顶的物理限制单独断言） |
| 2 | 开放/封闭耳模低频泄漏自动补偿 | 二阶高通 vent 模型（开放 fc≈500 Hz、封闭 fc≈150 Hz），在反馈稳定余量内自动补增益，残余泄漏如实上报 | `tests/test_2_leakage.py` | 7 项全过；开放耳 250 Hz 残余泄漏作为真实临床边界提示 |
| 3 | 模拟听损高频清晰度下降（不只是变小） | Baer & Moore (1993) ERB 高斯频谱展宽，按听阈映射展宽因子 1~6，保持总能量 | `tests/test_3_smearing.py` | 谱对比度显著下降、邻近峰变得不可分辨、能量守恒 |
| 4 | 1 分钟录音处理 ≤2 秒 | 全向量化 STFT 引擎（bincount 分带、数组化压缩/限幅/检测） | `tests/test_5_performance.py` | 60 s 音频 **约 1.5 s**（RTF≈0.025，预算 0.0334） |

另有啸叫自动检测/抑制专项测试 `tests/test_4_feedback.py`：干净语音 **0 误报**，
注入啸叫稳定检出（频率误差 < 半个 FFT bin）、陷波衰减 ≥10 dB、远离频点基本不受影响。

---

## 快速开始

```powershell
# 依赖 (当前环境已装): pip install -r requirements.txt

# 1. 生成演示音频 (合成类语音 + 1kHz 校准音)
py -3 make_demo.py

# 2. 命令行批处理
py -3 cli.py --audio samples/demo_speech.wav `
  --audiogram samples/audiogram_presbycusis.csv `
  --formula WDRC --fitting open --out-dir out

# 3. Web 界面 (家属 A/B 试听)
py -3 run_server.py
# 浏览器打开 http://127.0.0.1:8000
```

跑全部测试：

```powershell
py -3 -m pytest tests/ -q --ignore=tests/smoke_api.py
```

## Web 界面操作流程

1. **录入听力图**：10 个标准频率点（125~8000 Hz），可手动改或选预设（老年性聋/陡降型等）。
2. **选公式与耳模形式** → 计算通道增益，页面画出听力图曲线、8 通道目标增益、压缩比、
   泄漏衰减/补偿/残余泄漏表。
3. **上传录音** → 后端一次处理出助听前、助听后两个 wav。
4. **戴耳机 A/B 试听**：建议先放 1 kHz 校准音统一两耳音量，再公平比较两个版本。

---

## 目录结构

```
hearing_sim/
├── hearing_sim/            # DSP 核心库
│   ├── audiogram.py        # 听力图模型、对数频率插值、RETSPL、分级
│   ├── prescription.py     # NAL-R / NAL-RP / WDRC 处方公式
│   ├── filterbank.py       # 8 通道定义、LR4 交叉滤波、频域分带
│   ├── compressor.py       # 分通道 WDRC (attack/release、OSPL90)
│   ├── leakage.py          # 耳模 vent 泄漏建模与自动补偿
│   ├── feedback.py         # 啸叫检测 (LTA+邻域突起+时间稳态) 与高斯陷波
│   ├── smearing.py         # Baer-Moore ERB 频谱展宽
│   ├── loss_sim.py         # 助听前听损模拟 (阈下门限+重振响度映射+展宽)
│   ├── engine.py           # STFT 重叠相加引擎, 两条处理通路
│   ├── calibration.py      # 耳机声学校准音
│   ├── io_audio.py         # 音频读写/重采样
│   └── pipeline.py         # 高层管线与验配报告
├── web/                    # FastAPI 服务 + 单页前端
├── tests/                  # 32 项 pytest (对应四项需求) + API 冒烟测试
├── samples/                # 演示音频与示例听力图
├── make_demo.py            # 合成演示音频
├── cli.py                  # 命令行入口
└── run_server.py           # Web 服务入口
```

## 关键工程细节

- **电平链路**：内部统一 0 dBFS = 94 dB SPL。STFT 分带幅度经 Parseval 缩放
  （含实信号 rfft 的 √2 因子，已用已知 RMS 纯音标定到误差 <1%）还原时域等效 RMS，
  再进入 dB SPL 域的压缩与限幅，保证处方增益精确落地。
- **OSPL90**：在频域按带 RMS（不是单 bin 峰值谱级）逐带限制在不舒适阈 LDL 内，
  避免集中能量的纯音被误衰减。
- **啸叫检测**：在压缩**前**的输入谱上做（保留语音自然起伏），结合邻域突起、
  绝对电平门限、LTA 冻结和幅度时间变异系数 (CV<0.001)，区分稳态啸叫与颤动的语音谐波。
- **输入归一化**：RMS 拉到 −26 dBFS 工作点模拟助听器输入 AGC，给处方增益预留 headroom。

## 文献依据

- Byrne D, Dillon H. (1986). *The National Acoustic Laboratories' (NAL) new procedure for selecting the gain and frequency response of a hearing aid.* Ear and Hearing.
- Byrne D, Parkinson A, Kilpatrick D. (1991). NAL-RP 斜坡修正。
- Baer T, Moore BCJ. (1993). *Effects of spectral smearing on the intelligibility of sentences in noise.* JASA.
- Glasberg BR, Moore BCJ. (1990). ERB 带宽公式。
- Cornelisse LE, Seewald RC, Jamieson DG. (1995). DSL 宽动态范围压缩/响度归一化。
- Desloge JG et al. (1997); Clarity Challenge 听损可听化（Power Law / 响度映射）。
- Keidser G et al. (1999); Kuk F, Keidser G. (2006). 开放耳 vent 泄漏响应。
- Kates RM. (2001). *Feedback Cancellation in Hearing Aids.*
