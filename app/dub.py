"""AI dubbing: text-to-speech (edge-tts) for each translated phrase, placed on the clip timeline."""
import asyncio
import wave
from pathlib import Path

import numpy as np

from .languages import LANGUAGES
from .utils import run

SR = 24000


async def _synth_all(items, voice):
    import edge_tts

    for text, path in items:
        await edge_tts.Communicate(text, voice).save(str(path))


def _to_wav(src, dst, tempo=None):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", str(SR)]
    if tempo and tempo > 1.01:
        cmd += ["-filter:a", f"atempo={tempo:.3f}"]
    run(cmd + ["-c:a", "pcm_s16le", dst])


def _read_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def build_dub_track(phrases, lang_code, total_dur, work_dir: Path, name="dub") -> Path:
    """phrases: [{'text','start','end'}] on the OUTPUT timeline. Returns a wav as long as the clip."""
    voice = LANGUAGES[lang_code]["voice"]
    work_dir.mkdir(parents=True, exist_ok=True)
    items = [(p["text"], work_dir / f"{name}_{i}.mp3") for i, p in enumerate(phrases) if p["text"].strip()]
    asyncio.run(_synth_all(items, voice))

    track = np.zeros(int((total_dur + 2) * SR), dtype=np.float32)
    for i, p in enumerate(phrases):
        mp3 = work_dir / f"{name}_{i}.mp3"
        if not mp3.exists():
            continue
        wav = work_dir / f"{name}_{i}.wav"
        _to_wav(mp3, wav)
        audio = _read_wav(wav)
        nxt = phrases[i + 1]["start"] if i + 1 < len(phrases) else total_dur
        slot = max(nxt - p["start"], 0.3)
        dur = len(audio) / SR
        if dur > slot * 1.03:  # speak faster so it fits before the next phrase
            fast = work_dir / f"{name}_{i}_fast.wav"
            _to_wav(mp3, fast, tempo=min(dur / slot, 1.8))
            audio = _read_wav(fast)
        off = int(p["start"] * SR)
        end = min(len(track), off + len(audio))
        if end > off:
            track[off:end] += audio[: end - off]

    out = work_dir / f"{name}_track.wav"
    pcm = (np.clip(track, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())
    return out
