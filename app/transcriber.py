"""Speech-to-text with word-level timestamps (faster-whisper)."""
import threading

from . import config
from .models import Segment, Word

_model = None
_lock = threading.Lock()

FILLER_PROMPT = "Umm, let me think like, hmm... Okay, uh, here's what I'm, you know, thinking."


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(
                config.WHISPER_MODEL,
                device=config.WHISPER_DEVICE,
                compute_type=config.WHISPER_COMPUTE,
            )
        return _model


def transcribe(audio_path, language=None, keep_fillers=False, progress=None):
    """Return (segments, detected_language).

    keep_fillers: nudges Whisper (English only) to keep "umm"/"uh" in the transcript so
    they can be cut out later. Whisper normally drops them.
    """
    model = _get_model()
    prompt = FILLER_PROMPT if (keep_fillers and language == "en") else None
    segs, info = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        beam_size=5,
        initial_prompt=prompt,
    )
    total = max(info.duration or 0.0, 1.0)
    out = []
    for s in segs:  # generator: decoding happens while iterating
        words = [
            Word(w.start, w.end, w.word.strip())
            for w in (s.words or [])
            if w.word and w.word.strip()
        ]
        out.append(Segment(s.start, s.end, s.text.strip(), words))
        if progress:
            progress(min(1.0, s.end / total))
    return out, info.language
