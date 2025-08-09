import json
import re
import subprocess
from pathlib import Path
from typing import Optional


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def parse_loudnorm_json(text: str):
    lb = text.rfind("{")
    rb = text.rfind("}")
    if lb != -1 and rb != -1 and rb > lb:
        try:
            return json.loads(text[lb:rb + 1])
        except Exception:
            pass
    return None


def loudnorm_scan(path: Path) -> Optional[dict]:
    cmd = ["ffmpeg", "-nostats", "-hide_banner", "-i", str(path),
           "-filter:a", "loudnorm=I=-23:TP=-2:LRA=7:print_format=json:dual_mono=true",
           "-f", "null", "-"]
    proc = run(cmd)
    if proc.returncode != 0:
        return None
    return parse_loudnorm_json(proc.stderr)


def measure_sample_peak_dbfs(path: Path) -> Optional[float]:
    proc = run(["ffmpeg", "-nostats", "-hide_banner", "-i", str(path),
                "-af", "volumedetect", "-f", "null", "/dev/null"])
    m = re.search(r"max_volume:\s*([-\d\.]+)\s*dB", proc.stderr)
    if not m:
        return None
    return float(m.group(1))
