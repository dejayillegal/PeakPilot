from pathlib import Path
import json
import hashlib

def session_root(upload_root, session):
    """Return the Path to a session directory under upload_root."""
    return Path(upload_root) / session

def sha256sum(path):
    """Compute sha256 checksum of file at path."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def write_manifest(root: Path, manifest: dict):
    """Write manifest.json with checksums and sizes for files."""
    data = {}
    for key, meta in manifest.items():
        f = root / meta['filename']
        sha = sha256sum(f)
        size = f.stat().st_size
        data[key] = {**meta, 'sha256': sha, 'size': size}
    with open(root / 'manifest.json', 'w', encoding='utf-8') as fh:
        json.dump(data, fh)

def read_manifest(root: Path) -> dict:
    with open(root / 'manifest.json', 'r', encoding='utf-8') as fh:
        return json.load(fh)
