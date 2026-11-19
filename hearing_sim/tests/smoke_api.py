"""端到端 API 冒烟测试 (需先启动 run_server.py)。"""
import json
import urllib.parse
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"


def post_form(fields):
    data = urllib.parse.urlencode(fields).encode()
    return json.load(urllib.request.urlopen(
        urllib.request.Request(BASE + "/api/prescription", data=data)))


def post_multipart(fields, file_path):
    boundary = "----b" + uuid.uuid4().hex
    body = b""
    for name, val in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{val}\r\n").encode()
    wav = open(file_path, "rb").read()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; "
             f"filename=\"demo.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode()
    body += wav + b"\r\n" + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/process", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.load(urllib.request.urlopen(req))


if __name__ == "__main__":
    losses = "15,20,25,30,40,45,55,60,70,75"
    presc = post_form({"losses": losses, "formula": "WDRC", "fitting": "open"})
    print("prescription OK, severity:", presc["severity"], "stable:", presc["leakage_stable"])

    r = post_multipart(
        {"losses": losses, "formula": "WDRC", "fitting": "open",
         "feedback": "true", "smearing": "true"},
        "samples/demo_speech.wav")
    print("process OK, elapsed:", r["elapsed_s"], "RTF:", r["realtime_factor"],
          "howls:", r["howl_count"])
    for tag in ("unaided_url", "aided_url"):
        data = urllib.request.urlopen(BASE + r[tag]).read()
        assert data[:4] == b"RIFF", "WAV 头无效"
        print(tag, "->", len(data), "bytes, valid WAV")
    print("ALL API CHECKS PASSED")
