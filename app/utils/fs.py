import json
import os
import uuid
from pathlib import Path
from typing import Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
JOBS_DIR = BASE_DIR.parent / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

ALLOWED = {".wav", ".wave", ".aif", ".aiff", ".flac"}


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED


def create_job_dir() -> Tuple[str, Path]:
    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_id, job_dir


def write_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def read_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}
