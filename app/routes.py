import json
import zipfile
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from .services import ffmpeg
from .models import specs
from .utils import fs

bp = Blueprint("main", __name__)


@bp.route("/", methods=["GET"])
def index():
    return render_template("index.html")


def make_info_txt(out_path: Path, spec_line: str, metrics: dict) -> Path:
    info_path = out_path.with_name(out_path.stem + "_INFO.txt")
    with open(info_path, "w") as f:
        f.write(f"Output: {out_path.name}\n")
        f.write(f"Spec: {spec_line}\n")
        f.write("Measured (post):\n")
        for k, v in metrics.items():
            f.write(f"- {k}: {v}\n")
    return info_path


@bp.route("/process", methods=["POST"])
def process():
    files = request.files.getlist("audio")
    if not files or files[0].filename == "":
        flash("No files selected", "error")
        return redirect(url_for("main.index"))

    job_id, job_dir = fs.create_job_dir()
    job_log = {"id": job_id, "files": {}}
    results = []

    for file in files:
        if not fs.allowed_file(file.filename):
            flash(f"Unsupported file type: {file.filename}", "error")
            continue
        in_path = job_dir / file.filename
        file.save(in_path)
        per_file = {"outputs": []}

        try:
            out_club = job_dir / f"{Path(file.filename).stem}_ClubMaster_24b_48k.wav"
            m_club = ffmpeg.two_pass_loudnorm(in_path, specs.club, out_club)
            info = make_info_txt(
                out_club,
                "Club — 48 kHz, 24-bit WAV, target -7.5..-6.5 LUFS-I, TP ≤ -0.8 dBTP",
                m_club,
            )
            per_file["outputs"].append({"label": "Club Master", "file": out_club.name, "info": info.name})
            results.append({"label": "Club Master", "audio": out_club.name, "info": info.name})
        except Exception as e:
            per_file.setdefault("errors", []).append(f"Club: {e}")

        try:
            out_stream = job_dir / f"{Path(file.filename).stem}_StreamingMaster_24b_44k.wav"
            m_stream = ffmpeg.two_pass_loudnorm(in_path, specs.streaming, out_stream)
            info = make_info_txt(
                out_stream,
                "Streaming — 44.1 kHz, 24-bit WAV, target -10..-9 LUFS-I, TP ≤ -1.0 dBTP",
                m_stream,
            )
            per_file["outputs"].append({"label": "Streaming Master", "file": out_stream.name, "info": info.name})
            results.append({"label": "Streaming Master", "audio": out_stream.name, "info": info.name})
        except Exception as e:
            per_file.setdefault("errors", []).append(f"Streaming: {e}")

        try:
            out_pre = job_dir / f"{Path(file.filename).stem}_Premaster_Unlimited_24b_48k.wav"
            m_pre = ffmpeg.unlimited_premaster(in_path, out_pre)
            info = make_info_txt(
                out_pre,
                "Unlimited Premaster — 48 kHz, 24-bit WAV, limiter OFF, peaks ≈ -6 dBFS",
                m_pre,
            )
            per_file["outputs"].append({"label": "Unlimited Premaster", "file": out_pre.name, "info": info.name})
            results.append({"label": "Unlimited Premaster", "audio": out_pre.name, "info": info.name})
        except Exception as e:
            per_file.setdefault("errors", []).append(f"Unlimited: {e}")

        job_log["files"][file.filename] = per_file

    zip_path = job_dir / f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for p in job_dir.iterdir():
            if p.is_file() and p.name != zip_path.name:
                z.write(p, arcname=p.name)

    fs.write_json(job_dir / "job.json", job_log)
    return render_template("result.html", job_id=job_id, results=results, errors=[])


@bp.route("/download/<job_id>/<path:filename>")
def download(job_id, filename):
    job_dir = fs.JOBS_DIR / job_id
    if not job_dir.is_dir():
        abort(404)
    return send_from_directory(job_dir, filename, as_attachment=True)


@bp.route("/status/<job_id>.json")
def status(job_id):
    job_dir = fs.JOBS_DIR / job_id
    return jsonify(fs.read_json(job_dir / "job.json"))


@bp.route("/healthz")
def healthz():
    version = ffmpeg.ffmpeg_version()
    return jsonify({"ok": bool(version), "ffmpeg": version})


@bp.app_errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@bp.app_errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500
