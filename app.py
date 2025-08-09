
import os, re, json, math, uuid, shutil, tempfile, subprocess
from flask import Flask, render_template, request, send_from_directory, redirect, url_for, abort, flash

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-" + uuid.uuid4().hex
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
JOBS_DIR = os.path.join(BASE_DIR, "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

ALLOWED = {".wav", ".wave", ".aif", ".aiff", ".flac"}

def allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED

def run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, proc.stdout, proc.stderr

def parse_loudnorm_json(text: str):
    # find last JSON object in stderr
    lb = text.rfind("{")
    rb = text.rfind("}")
    if lb != -1 and rb != -1 and rb > lb:
        try:
            return json.loads(text[lb:rb+1])
        except Exception:
            pass
    return None

def loudnorm_scan(path: str):
    cmd = ["ffmpeg", "-nostats", "-hide_banner", "-i", path,
           "-filter:a", "loudnorm=I=-23:TP=-2:LRA=7:print_format=json:dual_mono=true",
           "-f", "null", "-"]
    rc, out, err = run(cmd)
    data = parse_loudnorm_json(err)
    return data

def loudnorm_two_pass(in_path: str, target_I: float, target_TP: float, target_LRA: float,
                      out_sr: int, out_path: str):
    # pass 1: measure
    m = loudnorm_scan(in_path)
    if not m:
        raise RuntimeError("Failed to measure loudness with ffmpeg/loudnorm.")
    params = {
        "I": target_I,
        "TP": target_TP,
        "LRA": target_LRA,
        "measured_I": m.get("input_i"),
        "measured_TP": m.get("input_tp"),
        "measured_LRA": m.get("input_lra"),
        "measured_thresh": m.get("input_thresh"),
        "offset": m.get("target_offset"),
        "linear": "true",
        "dual_mono": "true",
        "print_format": "json"
    }
    filt = "loudnorm=" + ":".join(f"{k}={v}" for k,v in params.items())
    cmd2 = ["ffmpeg", "-y", "-nostats", "-hide_banner", "-i", in_path,
            "-filter:a", filt, "-ar", str(out_sr), "-c:a", "pcm_s24le", out_path]
    rc, out2, err2 = run(cmd2)
    if rc != 0:
        raise RuntimeError("Normalization failed. ffmpeg said:\n" + err2)

    # measure output
    post = loudnorm_scan(out_path) or {}
    # duration via ffprobe
    rc3, out3, err3 = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=noprint_wrappers=1:nokey=1", out_path])
    dur = out3.strip() if rc3 == 0 else ""
    return {
        "integrated_lufs": post.get("input_i"),
        "true_peak_dbTP": post.get("input_tp"),
        "lra": post.get("input_lra"),
        "duration_s": dur
    }

def measure_sample_peak_dbfs(path: str):
    rc, out, err = run(["ffmpeg", "-nostats", "-hide_banner", "-i", path,
                        "-af", "volumedetect", "-f", "null", "/dev/null"])
    m = re.search(r"max_volume:\s*([-\d\.]+)\s*dB", err)
    if not m:
        return None
    return float(m.group(1))

def make_info_txt(out_path: str, spec_line: str, lines: list[str]):
    info_path = os.path.splitext(out_path)[0] + "_INFO.txt"
    with open(info_path, "w") as f:
        f.write(f"Output: {os.path.basename(out_path)}\n")
        f.write(f"Spec: {spec_line}\n")
        f.write("Measured (post):\n")
        for line in lines:
            f.write(f"- {line}\n")
    return info_path

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/process", methods=["POST"])
def process():
    if "audio" not in request.files:
        flash("No file part", "error")
        return redirect(url_for("index"))
    file = request.files["audio"]
    if file.filename == "":
        flash("No file selected", "error")
        return redirect(url_for("index"))
    if not allowed_file(file.filename):
        flash("Unsupported file type. Use WAV/AIFF/FLAC.", "error")
        return redirect(url_for("index"))

    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    in_name = file.filename
    in_path = os.path.join(job_dir, in_name)
    file.save(in_path)

    results = []
    errors = []

    # CLUB
    try:
        out_club = os.path.join(job_dir, os.path.splitext(in_name)[0] + "_ClubMaster_24b_48k.wav")
        m_club = loudnorm_two_pass(in_path, -7.2, -0.8, 7, 48000, out_club)
        info = make_info_txt(out_club,
            "Club — 48 kHz, 24-bit WAV, target -7.5..-6.5 LUFS-I, TP ≤ -0.8 dBTP",
            [
                f"Integrated Loudness (LUFS-I): {m_club.get('integrated_lufs')}",
                f"True Peak (dBTP): {m_club.get('true_peak_dbTP')}",
                f"Loudness Range (LRA): {m_club.get('lra')}",
                f"Duration (s): {m_club.get('duration_s')}",
            ]
        )
        results.append(("Club Master", os.path.basename(out_club), os.path.basename(info)))
    except Exception as e:
        errors.append(f"Club: {e}")

    # STREAMING
    try:
        out_stream = os.path.join(job_dir, os.path.splitext(in_name)[0] + "_StreamingMaster_24b_44k.wav")
        m_stream = loudnorm_two_pass(in_path, -9.5, -1.0, 9, 44100, out_stream)
        info = make_info_txt(out_stream,
            "Streaming — 44.1 kHz, 24-bit WAV, target -10..-9 LUFS-I, TP ≤ -1.0 dBTP",
            [
                f"Integrated Loudness (LUFS-I): {m_stream.get('integrated_lufs')}",
                f"True Peak (dBTP): {m_stream.get('true_peak_dbTP')}",
                f"Loudness Range (LRA): {m_stream.get('lra')}",
                f"Duration (s): {m_stream.get('duration_s')}",
            ]
        )
        results.append(("Streaming Master", os.path.basename(out_stream), os.path.basename(info)))
    except Exception as e:
        errors.append(f"Streaming: {e}")

    # UNLIMITED
    try:
        peak_db = measure_sample_peak_dbfs(in_path)
        if peak_db is None:
            gain_db = -6.0
        else:
            gain_db = -6.0 - peak_db  # move peak to -6 dBFS
        out_pre = os.path.join(job_dir, os.path.splitext(in_name)[0] + "_Premaster_Unlimited_24b_48k.wav")
        rc, outx, errx = run([
            "ffmpeg", "-y", "-nostats", "-hide_banner", "-i", in_path,
            "-filter:a", f"volume={gain_db:.3f}dB", "-ar", "48000", "-c:a", "pcm_s24le", out_pre
        ])
        # measure post
        post = loudnorm_scan(out_pre) or {}
        peak_post = measure_sample_peak_dbfs(out_pre)
        rc3, out3, err3 = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=noprint_wrappers=1:nokey=1", out_pre])
        dur = out3.strip() if rc3 == 0 else ""
        info = make_info_txt(out_pre,
            "Unlimited Premaster — 48 kHz, 24-bit WAV, limiter OFF, peaks ≈ -6.0 dBFS (sample peak)",
            [
                f"Sample Peak (dBFS): {peak_post}",
                f"Integrated Loudness (LUFS-I): {post.get('input_i')}",
                f"Approx True Peak (dBTP): {post.get('input_tp')}",
                f"Loudness Range (LRA): {post.get('input_lra')}",
                f"Duration (s): {dur}",
            ]
        )
        results.append(("Unlimited Premaster", os.path.basename(out_pre), os.path.basename(info)))
    except Exception as e:
        errors.append(f"Unlimited: {e}")

    return render_template("result.html", job_id=job_id, results=results, errors=errors)

@app.route("/download/<job_id>/<path:filename>")
def download(job_id, filename):
    job_dir = os.path.join(JOBS_DIR, job_id)
    if not os.path.isdir(job_dir):
        abort(404)
    return send_from_directory(job_dir, filename, as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
