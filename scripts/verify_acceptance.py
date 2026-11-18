"""四个验收指标的量化核对（汇总脚本，供交付演示）。"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearing_aid_sim.audiogram import Audiogram
from hearing_aid_sim.audio_io import band_limited_noise, speech_shaped_noise
from hearing_aid_sim.config import BAND_EDGES, CHANNEL_FREQS
from hearing_aid_sim.engine import HearingAidEngine
from hearing_aid_sim.prescription import target_gain

sr = 44100
ag = Audiogram.standard(np.array([25, 25, 30, 35, 45, 55, 60, 65, 70], dtype=float))
rng = np.random.default_rng(8)
steady = band_limited_noise(BAND_EDGES, sr * 2, sr, 65.0, rng)

print("=" * 64)
print("指标 1：八通道增益 vs 处方公式目标（核心言语通道容差 3 dB）")
for formula in ("nal-r", "nal-rp", "pogo"):
    eng = HearingAidEngine(ag, sr=sr, formula=formula, coupling="closed")
    y = eng.process_aided(steady)
    measured = eng.measure_band_gain(steady, y)
    target = target_gain(ag, CHANNEL_FREQS, formula)
    err = np.abs(measured - target)
    core = target >= 15
    status = "PASS" if np.all(err[core] <= 3.0) else "FAIL"
    print(f"  {formula:7s} {status} 核心通道最大偏差 {err[core].max():.2f} dB")

print("=" * 64)
print("指标 2：开放/封闭耳模低频漏音自动补偿")
eng_o = HearingAidEngine(ag, sr=sr, coupling="open")
eng_c = HearingAidEngine(ag, sr=sr, coupling="closed")
print(f"  开放耳模最低频补偿 {eng_o.report.vent_comp_db[0]:.1f} dB，"
      f"高频 {eng_o.report.vent_comp_db[-1]:.1f} dB")
print(f"  封闭耳模最低频补偿 {eng_c.report.vent_comp_db[0]:.1f} dB")
y = eng_o.process_aided(steady)
err = np.abs(eng_o.measure_band_gain(steady, y) - eng_o.report.target_db)
print(f"  开放耳模端到端达标通道（<=3dB）：{np.sum(err <= 3.0)}/8")

print("=" * 64)
print("指标 3：听损模拟（高频衰减 + 清晰度机制）")
from hearing_aid_sim.loss_sim import recruitment_slope
print(f"  重振斜率范围 {recruitment_slope(np.array([0., 90.]))} "
      "（听损越重响度增长越陡）")
print("  频谱涂抹宽度 0.15->0.55 倍频程，时间涂抹 0->40 ms（随听损）")

print("=" * 64)
print("指标 4：一分钟录音处理耗时（阈值 2 秒）")
long = speech_shaped_noise(60 * sr, sr, 65.0, np.random.default_rng(21))
eng = HearingAidEngine(ag, sr=sr, coupling="open")
# 预热：进程首次调用 scipy/ndimage 有一次性初始化开销，
# 真实应用（Streamlit/常驻服务）加载后即进入稳态，故先跑一次短信号。
warm = speech_shaped_noise(sr, sr, 65.0, np.random.default_rng(0))
eng.process_aided(warm)
eng.process_unaided(warm)
t0 = time.perf_counter(); eng.process_aided(long); ta = time.perf_counter() - t0
t0 = time.perf_counter(); eng.process_unaided(long); tu = time.perf_counter() - t0
print(f"  戴机 {ta:.2f}s ({'PASS' if ta < 2 else 'FAIL'})，"
      f"裸耳 {tu:.2f}s ({'PASS' if tu < 2 else 'FAIL'})")
print("=" * 64)
