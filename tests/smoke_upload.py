"""验证文件上传分支与两个输出 WAV 的内容合理性。"""
import io
import json
import sys
import urllib.request

import numpy as np
import soundfile as sf

sys.path.insert(0, r"D:\codex\runs\12529\workspace")
from hearing_sim import synth

BASE = "http://127.0.0.1:5000"
fs = 24000
rng = np.random.default_rng(11)
x = synth.speech_like_signal(5.0, fs, rng)
buf = io.BytesIO()
sf.write(buf, x, fs, format="WAV", subtype="PCM_16")
wav_bytes = buf.getvalue()

# 构造 multipart：文件 + 表单字段
boundary = "----upboundary99"
body = io.BytesIO()
def field(name, value):
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
    body.write(f"{value}\r\n".encode())
field("formula", "POGO")
field("mold_type", "closed")
field("ear", "left")
field("smearing", "1")
field("detect_feedback", "1")
freqs = [125, 250, 500, 1000, 2000, 3000, 4000, 6000, 8000]
hl = [20, 25, 35, 45, 60, 70, 78, 85, 90]
for f in freqs: field("freqs", f)
for v in hl: field("left_hl", v)
for v in hl: field("right_hl", v)
body.write(f"--{boundary}\r\n".encode())
body.write(b'Content-Disposition: form-data; name="audio"; filename="speech.wav"\r\n')
body.write(b"Content-Type: audio/wav\r\n\r\n")
body.write(wav_bytes)
body.write(f"\r\n--{boundary}--\r\n".encode())

req = urllib.request.Request(
    BASE + "/api/process", data=body.getvalue(),
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    method="POST")
with urllib.request.urlopen(req, timeout=60) as r:
    raw = r.read()
    b2 = r.headers["Content-Type"].split("boundary=")[1]

parts = {}
for ch in raw.split(("--" + b2).encode())[1:-1]:
    head, data = ch.split(b"\r\n\r\n", 1)
    name = head.decode("latin1").split('name="')[1].split('"')[0]
    parts[name] = data.rstrip(b"\r\n")

rep = json.loads(parts["report"].decode())
unaided, _ = sf.read(io.BytesIO(parts["unaided"]))
aided, fs2 = sf.read(io.BytesIO(parts["aided"]))

def rms_db(v):
    return 20 * np.log10(max(np.sqrt(np.mean(v**2)), 1e-12))

print(f"公式={rep['formula']} 耳模={rep['mold_type']} 封闭补偿通道0={rep['compensation_db'][0]:.1f}dB")
print(f"输入 RMS={rms_db(x):.1f}dBFS  裸耳 RMS={rms_db(unaided):.1f}dBFS  助听 RMS={rms_db(aided):.1f}dBFS")
print(f"裸耳可听内容占比(非静音帧): {np.mean(np.abs(unaided)>1e-4)*100:.0f}%")
print(f"助听增益体现: 助听RMS - 裸耳RMS = {rms_db(aided)-rms_db(unaided):.1f} dB")
assert rep["formula"] == "POGO" and rep["mold_type"] == "closed"
assert rms_db(unaided) < rms_db(x)          # 裸耳确实变差
assert rms_db(aided) > rms_db(unaided) + 10  # 助听明显补偿
assert np.any(np.abs(unaided) > 1e-3)        # 裸耳不是全静音
print("\n文件上传分支与双版本内容合理性验证通过。")
