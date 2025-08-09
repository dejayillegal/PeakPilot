import os

OUTPUT_CODEC = os.getenv("OUTPUT_CODEC", "wav")
DEFAULT_TARGETS = {
    "club": {"I": -7.2, "TP": -0.8, "LRA": 7, "sr": 48000},
    "streaming": {"I": -9.5, "TP": -1.0, "LRA": 9, "sr": 44100},
}
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "200"))
CLEAN_JOBS_AFTER_HOURS = int(os.getenv("CLEAN_JOBS_AFTER_HOURS", "24"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
