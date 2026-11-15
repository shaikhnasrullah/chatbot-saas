"""Subtitle translation with Claude."""
import json
import logging

from . import llm
from .highlights import parse_json_block
from .languages import LANGUAGES

log = logging.getLogger("clipper.translate")

BATCH = 30

SYSTEM = """You are a professional subtitle translator.
Translate every numbered line into {language}. Keep the meaning and the natural spoken tone,
keep each line short, keep names and brand names unchanged.
{extra}
Return ONLY a JSON array of strings with exactly {n} items, in the same order. No commentary."""

HINGLISH_NOTE = (
    "Write Hindi in Roman (Latin) letters the way Indians type on WhatsApp "
    "(e.g. 'Yeh bahut zaroori hai'). Do not use Devanagari."
)


def _translate_batch(texts, language, extra):
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    raw = llm.complete(SYSTEM.format(language=language, extra=extra, n=len(texts)), numbered, max_tokens=4000)
    data = parse_json_block(raw)
    if not isinstance(data, list) or len(data) != len(texts):
        raise ValueError("Translation count mismatch")
    return [str(x).strip() for x in data]


def _safe_batch(texts, language, extra):
    try:
        return _translate_batch(texts, language, extra)
    except (ValueError, json.JSONDecodeError) as exc:
        if len(texts) == 1:
            log.warning("Could not translate one line (%s); keeping original.", exc)
            return list(texts)
        mid = len(texts) // 2  # split and retry so one bad batch doesn't lose everything
        return _safe_batch(texts[:mid], language, extra) + _safe_batch(texts[mid:], language, extra)


def translate_texts(texts, lang_code):
    """Translate a list of strings into the language `lang_code` (key of LANGUAGES)."""
    if lang_code not in LANGUAGES:
        raise ValueError(f"Unknown language: {lang_code}")
    language = LANGUAGES[lang_code]["name"]
    extra = HINGLISH_NOTE if lang_code == "hinglish" else ""
    out = []
    for i in range(0, len(texts), BATCH):
        out.extend(_safe_batch(texts[i:i + BATCH], language, extra))
    return out
