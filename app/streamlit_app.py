"""助听器验配模拟 —— 家属试听界面（Streamlit）。

启动：
  py -m streamlit run app/streamlit_app.py

功能：
- 录入/上传听力图（9 点 dB HL 滑杆，或导入 JSON）
- 选择处方公式（NAL-R/NAL-RP/POGO）与耳模（开放/封闭）
- 上传录音或用内置演示信号，一键生成裸耳/戴机两个版本
- 展示八通道增益、漏音补偿、啸叫频点、处理耗时
- 双版本音频播放器 + 增益曲线/听力图
"""

import io
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearing_aid_sim.audiogram import Audiogram
from hearing_aid_sim.audio_io import (load_audio, save_audio,
                                      speech_shaped_noise, pure_tone)
from hearing_aid_sim.config import (AUDIOGRAM_FREQS, CHANNEL_FREQS,
                                    DEFAULT_SR)
from hearing_aid_sim.engine import HearingAidEngine

st.set_page_config(page_title="助听器验配模拟", layout="wide")

PRESET_HL = {
    "正常听力": [0] * 9,
    "平坦轻度（35 dB）": [35] * 9,
    "老年高频下降型": [25, 25, 30, 35, 45, 55, 60, 65, 70],
    "重度平坦型": [60, 60, 62, 65, 68, 70, 72, 75, 78],
}


def sidebar_audiogram() -> Audiogram:
    st.sidebar.header("① 听力图（dB HL）")
    preset = st.sidebar.selectbox("快速预设", list(PRESET_HL.keys()))
    uploaded = st.sidebar.file_uploader("或导入听力图 JSON", type=["json"])
    if uploaded is not None:
        data = json.loads(uploaded.read().decode("utf-8"))
        vals = list(data["hl"])
        st.sidebar.caption("已导入 JSON 听力图")
    else:
        vals = list(PRESET_HL[preset])
    hl = []
    for f, v in zip(AUDIOGRAM_FREQS, vals):
        hl.append(st.sidebar.slider(
            f"{int(f)} Hz", -10, 110, int(v), key=f"hl_{f}"))
    ear = st.sidebar.radio("耳别", ["right", "left"], horizontal=True)
    return Audiogram.standard(np.array(hl, dtype=float), ear=ear)


def sidebar_config():
    st.sidebar.header("② 验配参数")
    formula = st.sidebar.selectbox("处方公式", ["nal-r", "nal-rp", "pogo"])
    coupling = st.sidebar.selectbox(
        "耳模类型", ["open", "closed"],
        format_func=lambda c: "开放耳模" if c == "open" else "封闭耳模")
    feedback = st.sidebar.checkbox("啸叫自动检测与陷波", value=True)
    return formula, coupling, feedback


def get_input_audio(sr):
    st.header("③ 录音输入")
    up = st.file_uploader("上传录音（wav/flac/ogg）",
                          type=["wav", "flac", "ogg"])
    col1, col2 = st.columns(2)
    use_demo = col1.button("用内置言语演示信号（5 秒）")
    use_howl = col2.button("用含啸叫演示信号（5 秒，3150 Hz）")
    if up is not None:
        with tempfile.NamedTemporaryFile(suffix=Path(up.name).suffix,
                                         delete=False) as tmp:
            tmp.write(up.read())
            tmp_path = tmp.name
        x, file_sr = load_audio(tmp_path, target_sr=sr)
        return x, f"上传文件 {Path(up.name).name}"
    if use_demo or use_howl:
        rng = np.random.default_rng(7)
        n = sr * 5
        x = speech_shaped_noise(n, sr, 65.0, rng)
        if use_howl:
            x = x + pure_tone(3150.0, sr, 78.0, n=n)
        return x, "内置演示信号" + ("（含啸叫）" if use_howl else "")
    return None, None


def wav_bytes(x, sr) -> bytes:
    buf = io.BytesIO()
    save_audio(buf, x, sr)
    return buf.getvalue()


def main():
    st.title("助听器验配模拟系统")
    st.caption("导入听力图 → 八通道处方增益 → 轻声/大声 WDRC 压缩 → "
               "开放耳漏音补偿 → 啸叫自动抑制 → 双版本试听")

    ag = sidebar_audiogram()
    formula, coupling, feedback = sidebar_config()
    sr = DEFAULT_SR
    x, source_name = get_input_audio(sr)

    # 听力图与分级信息
    c1, c2, c3 = st.columns(3)
    c1.metric("纯音平均 PTA", f"{ag.pta():.0f} dB HL")
    c2.metric("听损分级", ag.degree())
    c3.metric("耳别", "右耳" if ag.ear == "right" else "左耳")

    if x is None:
        st.info("请上传录音或点击演示信号按钮开始。")
        return

    st.header("④ 处理与试听")
    eng = HearingAidEngine(ag, sr=sr, formula=formula, coupling=coupling,
                           enable_feedback=feedback)
    t0 = time.perf_counter()
    y_aided = eng.process_aided(x)
    t_aided = time.perf_counter() - t0
    t0 = time.perf_counter()
    y_unaided = eng.process_unaided(x)
    t_unaided = time.perf_counter() - t0
    r = eng.report

    m1, m2, m3 = st.columns(3)
    m1.metric("戴机处理耗时", f"{t_aided:.2f} s")
    m2.metric("裸耳模拟耗时", f"{t_unaided:.2f} s")
    m3.metric("检出啸叫频点",
              ", ".join(f"{h.freq_hz:.0f}Hz" for h in r.howls) or "无")

    tab1, tab2 = st.tabs(["🎧 双版本试听", "📈 验配参数与曲线"])
    with tab1:
        cc1, cc2 = st.columns(2)
        with cc1:
            st.subheader("老人现在听到的（裸耳）")
            st.audio(wav_bytes(y_unaided, sr), sample_rate=sr)
        with cc2:
            st.subheader("戴上助听器以后（戴机）")
            st.audio(wav_bytes(y_aided, sr), sample_rate=sr)
        st.caption(f"信号来源：{source_name}。建议戴耳机在安静环境试听，"
                   "两个版本用相同音量回放以便对比。")

    with tab2:
        df = pd.DataFrame({
            "通道中心频率 Hz": np.round(CHANNEL_FREQS).astype(int),
            "听损 dB HL": np.round(eng.hl_channels, 1),
            "处方目标 dB": np.round(r.prescription_db, 1),
            "耳模漏音 dB": np.round(r.vent_loss_db, 1),
            "漏音补偿 dB": np.round(r.vent_comp_db, 1),
            "最终目标 dB": np.round(r.target_db, 1),
        })
        st.dataframe(df, use_container_width=True, hide_index=True)
        chart_df = pd.DataFrame({
            "频率 Hz": CHANNEL_FREQS,
            "处方目标": r.prescription_db,
            "漏音补偿后目标": r.target_db,
        }).set_index("频率 Hz")
        st.line_chart(chart_df)
        ag_df = pd.DataFrame({
            "频率 Hz": AUDIOGRAM_FREQS,
            "听阈 dB HL": ag.hl_at(AUDIOGRAM_FREQS),
        }).set_index("频率 Hz")
        st.caption("听力图")
        st.line_chart(ag_df)


if __name__ == "__main__":
    main()
