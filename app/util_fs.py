import os
import json
import hashlib
import shutil
import uuid
import tempfile
from typing import Dict, Tuple

ALLOWED_EXTS = {'.wav', '.aiff', '.aif', '.flac', '.mp3'}


def generate_session() -> str:
    """Return a random short session identifier."""
    return uuid.uuid4().hex[:12]


def safe_join(base: str, *paths: str) -> str:
    """Safely join one or more path components to ``base``.

    Raises ``ValueError`` if the resulting path is outside ``base``.
    """
    base_abs = os.path.abspath(base)
    joined = os.path.abspath(os.path.join(base, *paths))
    if not joined.startswith(base_abs + os.sep):
        raise ValueError("Unsafe path")
    return joined


def write_json_atomic(path: str, data: Dict) -> None:
    """Atomically write JSON data to ``path``."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def read_json(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def sha256_file(path: str) -> str:
    """Return hex sha256 of file at ``path``."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_session(root: str, session: str) -> str:
    """Ensure session directory exists and return its path."""
    path = os.path.join(root, session)
    os.makedirs(path, exist_ok=True)
    return path


def clear_session(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def manifest_path(session_dir: str) -> str:
    return os.path.join(session_dir, 'manifest.json')


def progress_path(session_dir: str) -> str:
    return os.path.join(session_dir, 'progress.json')


def write_progress(session_dir: str, data: Dict) -> None:
    write_json_atomic(progress_path(session_dir), data)


def get_input_path(session_dir: str) -> str | None:
    for ext in ALLOWED_EXTS:
        p = os.path.join(session_dir, f'input{ext}')
        if os.path.exists(p):
            return p
    return None


def save_upload(file_storage, session_dir: str) -> Tuple[str, int]:
    """Save uploaded file to ``session_dir`` as ``input.<ext>``.

    Returns tuple of (path, size).
    """
    filename = file_storage.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError('unsupported file type')

    os.makedirs(session_dir, exist_ok=True)
    input_path = os.path.join(session_dir, f'input{ext}')
    file_storage.save(input_path)
    size = os.path.getsize(input_path)
    with open(os.path.join(session_dir, 'meta.txt'), 'w', encoding='utf-8') as fh:
        fh.write(filename)
    return input_path, size


def load_manifest(session_dir: str) -> Dict:
    path = manifest_path(session_dir)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    return {}


def write_manifest(session_dir: str, manifest: Dict) -> None:
    write_json_atomic(manifest_path(session_dir), manifest)
