"""Download a YouTube video with yt-dlp."""
from pathlib import Path
from urllib.parse import urlparse

from . import config


def validate_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise ValueError("Ek valid YouTube link daalo (https://...).")
    if config.ALLOWED_HOSTS and host not in config.ALLOWED_HOSTS:
        raise ValueError("Abhi sirf YouTube links allowed hain.")
    return url


def download(url: str, out_dir: Path, progress=None):
    """Download best video+audio (<=1080p) as source.mp4. Returns (path, meta)."""
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)

    def hook(d):
        if d.get("status") == "downloading" and progress:
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    if config.YTDLP_COOKIES:
        opts["cookiefile"] = config.YTDLP_COOKIES

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get("is_live"):
            raise ValueError("Live stream ke clips nahi ban sakte.")
        duration = info.get("duration") or 0
        if duration > config.MAX_VIDEO_MINUTES * 60:
            raise ValueError(f"Video {config.MAX_VIDEO_MINUTES} minute se lamba hai.")
        ydl.download([url])

    files = sorted(out_dir.glob("source.*"), key=lambda p: (p.suffix != ".mp4", p.name))
    if not files:
        raise RuntimeError("Download ke baad video file nahi mili.")
    meta = {"title": info.get("title", ""), "duration": duration, "id": info.get("id", "")}
    return files[0], meta
