"""端到端 HTTP 接口冒烟测试：真实启动 Flask 后运行（非 pytest 单元测试）。"""
import io
import json
import sys
import urllib.request

import soundfile as sf

BASE = "http://127.0.0.1:5000"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.status, r.read()


def post_json(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_multipart(raw, boundary):
    delim = b"--" + boundary.encode()
    parts = {}
    chunks = raw.split(delim)
    for ch in chunks[1:-1]:
        if b"\r\n\r\n" not in ch:
            continue
        head, body = ch.split(b"\r\n\r\n", 1)
        head = head.decode("latin1")
        name = head.split('name="')[1].split('"')[0]
        parts[name] = body.rstrip(b"\r\n")
    return parts


def main():
    # 1. 首页
    st, html = get("/")
    assert st == 200 and "助听器验配" in html.decode("utf-8"), "首页异常"
    print("[OK] GET / 首页")

    # 2. 预设
    st, body = get("/api/presets")
    presets = json.loads(body)
    assert "轻度老年性聋(高频缓降)" in presets["presets"]
    print(f"[OK] GET /api/presets，{len(presets['presets'])} 个预设")

    ag = {
        "freqs": presets["freqs"],
        "left_hl": presets["presets"]["中重度高频陡降"],
        "right_hl": presets["presets"]["中重度高频陡降"],
    }

    # 3. 验配方案
    fit = post_json("/api/fit", {**ag, "formula": "NAL-R", "mold_type": "open"})
    rep = fit["report"]
    assert len(rep["target_gains_db"]) == 8
    assert rep["vent_fc_hz"] == 500.0
    assert all(c >= 0 for c in rep["capped_channels"])
    print("[OK] POST /api/fit，8 通道目标:",
          [round(g, 1) for g in rep["target_gains_db"]])

    # 4. 音频处理（multipart 手工构造，走内置演示信号 + 注入啸叫）
    boundary = "----testboundary123"
    lines = []
    def field(name, value):
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(str(value).encode())
    field("formula", "NAL-R")
    field("mold_type", "open")
    field("ear", "left")
    field("smearing", "1")
    field("detect_feedback", "1")
    field("demo_seconds", "6")
    field("demo_seed", "5")
    field("inject_howl", "1")
    for f in ag["freqs"]:
        field("freqs", f)
    for v in ag["left_hl"]:
        field("left_hl", v)
    for v in ag["right_hl"]:
        field("right_hl", v)
    lines.append(f"--{boundary}--".encode())
    body = b"\r\n".join(lines)

    req = urllib.request.Request(
        BASE + "/api/process", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = r.headers["Content-Type"]
        raw = r.read()
    b2 = ctype.split("boundary=")[1]
    parts = parse_multipart(raw, b2)
    assert {"report", "unaided", "aided"} <= set(parts), f"分片缺失: {list(parts)}"
    report = json.loads(parts["report"].decode("utf-8"))

    for name in ("unaided", "aided"):
        data, fs = sf.read(io.BytesIO(parts[name]))
        assert fs == 24000 and len(data) > 24000 * 5
        assert abs(data).max() <= 1.0
        print(f"[OK] {name}.wav: fs={fs}, 时长={len(data)/fs:.1f}s, 峰值={abs(data).max():.2f}")

    print(f"[OK] 处理耗时 {report['processing_seconds']:.2f}s, "
          f"实时 {report['realtime_ratio']:.1f}x, 啸叫点 {len(report['howls'])} 个, "
          f"陷波 {[round(f) for f in report['notch_freqs']]}")
    assert report["processing_seconds"] < 2.0
    assert len(report["howls"]) >= 2
    print("\n全部 HTTP 接口端到端验证通过。")


if __name__ == "__main__":
    sys.path.insert(0, r"D:\codex\runs\12529\workspace")
    main()
