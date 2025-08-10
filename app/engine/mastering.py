import os
import subprocess
import time
from pathlib import Path
from typing import Callable, List

import soundfile as sf

from ..pipeline import update_progress


def probe_duration_seconds(path: str) -> float:
    """Return duration of ``path`` in seconds using ``soundfile``."""
    with sf.SoundFile(path) as f:
        return f.frames / f.samplerate


def run_ffmpeg_with_progress(args: List[str], duration_s: float, update: Callable[[int], None], cwd: str | None = None):
    """Run ffmpeg with ``-progress`` and forward percentage to ``update``."""
    args = list(args)
    args[-1:-1] = ["-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, text=True, bufsize=1)
    last_pct = -1
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            if line.startswith("out_time_ms="):
                ms = int(line.split("=", 1)[1].strip() or 0)
                pct = int(min(99, (ms / 1_000_000.0) / max(0.001, duration_s) * 100))
                if pct != last_pct:
                    last_pct = pct
                    update(pct)
    finally:
        proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"ffmpeg failed: {err[-800:]}")


def _render_master(target: str, in_path: Path, out_path: Path, args_for_ffmpeg: List[str], masters: dict, sess_dir: str):
    """Render a single master with progress updates."""
    dur = probe_duration_seconds(str(in_path))
    masters[target].update({"state": "rendering", "pct": 0, "message": "Rendering..."})
    update_progress(sess_dir, masters={target: masters[target]})

    def onp(pct: int):
        masters[target].update({"pct": pct})
        update_progress(sess_dir, masters={target: masters[target]})

    part = out_path.with_suffix(out_path.suffix + ".part")
    args = args_for_ffmpeg[:-1] + [str(part)]
    run_ffmpeg_with_progress(args, dur, onp)
    masters[target].update({"state": "finalizing", "message": "Finalizing..."})
    update_progress(sess_dir, masters={target: masters[target]})
    os.replace(part, out_path)
    masters[target].update({"state": "done", "pct": 100, "message": "Ready"})
    update_progress(sess_dir, masters={target: masters[target]})

