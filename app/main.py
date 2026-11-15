"""FastAPI server: job API + static frontend.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import json
import logging
import os
import re
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import config, llm
from .downloader import validate_url
from .languages import LANGUAGES
from .pipeline import run_pipeline

log = logging.getLogger("clipper")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Clipper")
executor = ThreadPoolExecutor(max_workers=config.WORKERS)
_lock = threading.Lock()
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
FILE_RE = re.compile(r"^[\w\-]+\.(mp4|srt)$")
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


class JobRequest(BaseModel):
    url: str
    lengths: list[int] = [60, 120]
    per_length: int = Field(2, ge=1, le=5)
    source_lang: Optional[str] = None  # None = auto-detect
    target_lang: Optional[str] = None
    caption_mode: Literal["original", "translated", "both", "none"] = "original"
    vertical: bool = True
    vertical_mode: Literal["face", "blur"] = "face"
    remove_fillers: bool = True
    trim_silence: bool = True
    music: Optional[str] = None
    music_volume: float = Field(0.12, ge=0.0, le=1.0)
    dub: bool = False
    show_title: bool = True

    @field_validator("lengths")
    @classmethod
    def _lengths(cls, v):
        v = sorted({int(x) for x in v})
        if not v or any(x < 15 or x > 300 for x in v):
            raise ValueError("Har length 15 se 300 seconds ke beech honi chahiye.")
        return v[:4]


def _list_music():
    if not config.MUSIC_DIR.is_dir():
        return []
    return sorted(p.name for p in config.MUSIC_DIR.iterdir() if p.suffix.lower() in MUSIC_EXT)


# ---------- job storage (JSON on disk, so restarts don't lose results) ----------

def _job_file(job_id: str) -> Path:
    return config.JOBS_DIR / job_id / "job.json"


def _read_job(job_id: str) -> Optional[dict]:
    if not JOB_ID_RE.match(job_id):
        return None
    try:
        return json.loads(_job_file(job_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _update_job(job_id: str, **changes):
    with _lock:
        data = _read_job(job_id) or {}
        data.update({k: v for k, v in changes.items() if v is not None})
        path = _job_file(job_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def _worker(job_id: str, req: JobRequest):
    def report(progress=None, message=None, status=None, **extra):
        _update_job(job_id, progress=progress, message=message, status=status, **extra)

    music_path = str(config.MUSIC_DIR / req.music) if req.music else None
    try:
        run_pipeline(config.JOBS_DIR / job_id, req, report, music_path)
    except Exception as exc:
        log.error("Job %s failed:\n%s", job_id, traceback.format_exc())
        _update_job(job_id, status="error", message=str(exc), error=str(exc))


# ---------- API ----------

@app.get("/api/config")
def get_config():
    return {
        "languages": [{"code": c, "name": v["name"]} for c, v in LANGUAGES.items()],
        "music": _list_music(),
        "llm_ready": llm.available(),
        "max_minutes": config.MAX_VIDEO_MINUTES,
    }


@app.post("/api/jobs")
def create_job(req: JobRequest):
    try:
        req.url = validate_url(req.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if req.target_lang and req.target_lang not in LANGUAGES:
        raise HTTPException(400, "Yeh translation language supported nahi hai.")
    if req.source_lang and req.source_lang not in LANGUAGES:
        req.source_lang = None
    if req.music and req.music not in _list_music():
        raise HTTPException(400, "Yeh music file nahi mili.")
    if (req.dub or req.caption_mode in ("translated", "both")) and not req.target_lang:
        raise HTTPException(400, "Translated captions ya dubbing ke liye target language chuno.")
    if req.target_lang and (req.dub or req.caption_mode in ("translated", "both")) and not llm.available():
        raise HTTPException(400, "Translation ke liye ANTHROPIC_API_KEY .env mein set karo.")

    job_id = uuid.uuid4().hex
    (config.JOBS_DIR / job_id).mkdir(parents=True, exist_ok=True)
    _update_job(job_id, id=job_id, status="queued", progress=0, message="Queue mein hai…",
                clips=[], url=req.url)
    executor.submit(_worker, job_id, req)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = _read_job(job_id)
    if not job:
        raise HTTPException(404, "Job nahi mila.")
    return job


@app.get("/api/jobs/{job_id}/clips/{name}")
def get_clip(job_id: str, name: str, download: bool = False):
    if not JOB_ID_RE.match(job_id) or not FILE_RE.match(name):
        raise HTTPException(404)
    path = config.JOBS_DIR / job_id / "clips" / name
    if not path.is_file():
        raise HTTPException(404)
    media = "video/mp4" if name.endswith(".mp4") else "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media, filename=name if download else None,
                        content_disposition_type="attachment" if download else "inline")


config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
config.MUSIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
