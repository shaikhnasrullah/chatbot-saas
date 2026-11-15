"""Central configuration, read from environment variables (a .env file is supported)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CLIPPER_DATA", BASE_DIR / "data"))
JOBS_DIR = DATA_DIR / "jobs"
MUSIC_DIR = Path(os.getenv("MUSIC_DIR", BASE_DIR / "music"))
STATIC_DIR = BASE_DIR / "static"

# --- LLM (clip selection + translation) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

# --- Speech to text (faster-whisper) ---
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")  # tiny/base/small/medium/large-v3
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")  # auto/cpu/cuda
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "auto")  # auto/int8/float16

# --- Limits and behaviour ---
MAX_VIDEO_MINUTES = int(os.getenv("MAX_VIDEO_MINUTES", "60"))
WORKERS = int(os.getenv("WORKERS", "1"))
KEEP_SOURCE = os.getenv("KEEP_SOURCE", "0") == "1"
ALLOWED_HOSTS = [
    h.strip().lower()
    for h in os.getenv(
        "ALLOWED_HOSTS",
        "youtube.com,www.youtube.com,m.youtube.com,music.youtube.com,youtu.be",
    ).split(",")
    if h.strip()
]

# --- Captions ---
CAPTION_FONT = os.getenv("CAPTION_FONT", "Arial")
CAPTION_FONTS_DIR = os.getenv("CAPTION_FONTS_DIR", "")  # optional folder with .ttf files

# --- yt-dlp ---
YTDLP_COOKIES = os.getenv("YTDLP_COOKIES", "")  # optional path to a cookies.txt file
