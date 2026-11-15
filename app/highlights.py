"""Pick the best 1-minute / 2-minute moments from a transcript.

Primary: Claude chooses clips (hook, complete thought). Fallback: a local heuristic
score, so the app still works without an API key or if the LLM call fails.
"""
import json
import re
import logging

from . import llm
from .models import ClipPlan, Segment

log = logging.getLogger("clipper.highlights")

KEYWORDS = (
    "secret", "mistake", "never", "always", "truth", "biggest", "best", "worst",
    "important", "why", "how to", "reason", "story", "lesson", "problem", "money",
    "free", "first", "stop", "warning", "actually", "crazy", "amazing",
    "kyun", "kaise", "sabse", "zaroor", "galti", "raaz",
)

SYSTEM_PROMPT = """You are an expert short-form video editor (YouTube Shorts / Reels / TikTok).
You receive a timestamped transcript and choose the most engaging, self-contained clips.

Rules:
- Every clip must open on a strong hook (a bold claim, question, story start or surprise) and
  start at the beginning of a sentence.
- Every clip must end after a complete thought, never mid-sentence.
- Clip length must be close to its target length (within about 15%).
- Clips must not overlap each other and must lie inside the transcript timeline.
- start/end are seconds and should match the transcript's segment boundaries.
- title: catchy, max 60 characters, written in {title_language}.
- reason: one short sentence on why this moment works.
- score: integer 1-10 for viral potential.

Return ONLY valid JSON, no commentary:
{{"clips": [{{"target": 60, "start": 12.4, "end": 71.9, "title": "...", "reason": "...", "score": 8}}]}}"""


# ---------- helpers ----------

def parse_json_block(text: str):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    ends = [i for i in (text.rfind("}"), text.rfind("]")) if i != -1]
    if not starts or not ends:
        raise ValueError("LLM ne valid JSON nahi diya.")
    return json.loads(text[min(starts): max(ends) + 1])


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _snap(start, end, segments):
    ns = min((s.start for s in segments), key=lambda x: abs(x - start))
    ne = min((s.end for s in segments), key=lambda x: abs(x - end))
    return ns, ne


def _fit_length(start, end, target, segments, lo=0.7, hi=1.3):
    """Move `end` to a segment boundary so the clip is close to `target`. None if impossible."""
    dur = end - start
    if lo * target <= dur <= hi * target:
        return end
    ideal = start + target
    candidates = [s.end for s in segments if s.end > start + lo * target and s.end <= start + hi * target]
    if not candidates:
        return None
    return min(candidates, key=lambda e: abs(e - ideal))


# ---------- LLM selection ----------

def llm_select(segments, duration, lengths, per_length, title_language):
    lines = "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in segments)
    user = (
        f"Video duration: {duration:.0f} seconds.\n"
        f"Pick {per_length} clip(s) for EACH of these target lengths (seconds): {lengths}. "
        f"Set \"target\" in each clip to the length bucket it belongs to.\n\n"
        f"TRANSCRIPT:\n{lines}"
    )
    raw = llm.complete(SYSTEM_PROMPT.format(title_language=title_language), user, max_tokens=4000)
    data = parse_json_block(raw)
    return data["clips"] if isinstance(data, dict) else data


def finalize(raw_clips, segments, duration, lengths):
    """Validate / snap / de-duplicate clips returned by the LLM."""
    plans = []
    for c in raw_clips or []:
        try:
            start, end = float(c["start"]), float(c["end"])
            target = int(c.get("target") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if target not in lengths:  # assign to the nearest requested length
            target = min(lengths, key=lambda L: abs(L - (end - start)))
        start, end = max(0.0, start), min(duration, end)
        if end <= start:
            continue
        start, end = _snap(start, end, segments)
        fixed_end = _fit_length(start, end, target, segments)
        if fixed_end is None or fixed_end <= start:
            continue
        plans.append(ClipPlan(
            start=start, end=fixed_end,
            title=str(c.get("title", "")).strip()[:80],
            reason=str(c.get("reason", "")).strip(),
            score=float(c.get("score") or 0), target=target,
        ))
    return _dedupe(plans)


def _dedupe(plans):
    kept = []
    for p in sorted(plans, key=lambda x: -x.score):
        if not any(_overlaps(p.start, p.end, k.start, k.end) for k in kept):
            kept.append(p)
    return kept


# ---------- heuristic fallback ----------

def _score_text(text: str, dur: float) -> float:
    words = text.split()
    if not words or dur <= 0:
        return 0.0
    lower = text.lower()
    density = len(words) / dur  # talk speed
    kw = sum(lower.count(k) for k in KEYWORDS)
    return min(density, 4.0) + 1.5 * text.count("?") + 0.7 * text.count("!") + 0.8 * kw


def heuristic_clips(segments, target, count, exclude=()):
    """Sliding windows of ~target seconds over segment boundaries; greedy non-overlapping top-N."""
    cands = []
    for i, first in enumerate(segments):
        text, j = "", i
        while j < len(segments) and segments[j].end - first.start <= target * 1.2:
            text += " " + segments[j].text
            j += 1
            dur = segments[j - 1].end - first.start
            if dur >= target * 0.85:
                hook = 1.0 if ("?" in first.text or first.text.rstrip().endswith("!")) else 0.0
                cands.append((_score_text(text, dur) + hook, first.start, segments[j - 1].end, first.text))
                break
    cands.sort(reverse=True)
    picked = []
    for score, s, e, first_text in cands:
        if any(_overlaps(s, e, x, y) for x, y in exclude):
            continue
        if any(_overlaps(s, e, p.start, p.end) for p in picked):
            continue
        title = first_text.strip()[:60]
        picked.append(ClipPlan(s, e, title, "Local heuristic pick", round(score, 2), target))
        if len(picked) >= count:
            break
    return picked


# ---------- entry point ----------

def pick_clips(segments: list[Segment], duration: float, lengths, per_length, title_language="the transcript language"):
    lengths = sorted({int(L) for L in lengths if int(L) >= 15})
    lengths = [L for L in lengths if duration >= 0.8 * L]
    if not lengths:  # video shorter than every requested length -> one clip of the whole video
        whole = int(duration)
        return [ClipPlan(segments[0].start, segments[-1].end, segments[0].text[:60], "Whole video", 5, whole)]

    plans = []
    if llm.available():
        try:
            raw = llm_select(segments, duration, lengths, per_length, title_language)
            plans = finalize(raw, segments, duration, lengths)
        except Exception as exc:  # network, bad JSON, ...
            log.warning("LLM clip selection failed, using heuristic: %s", exc)

    taken = [(p.start, p.end) for p in plans]
    for L in lengths:
        have = [p for p in plans if p.target == L]
        # keep at most per_length from the LLM for each bucket
        for extra in sorted(have, key=lambda p: -p.score)[per_length:]:
            plans.remove(extra)
        need = per_length - min(len(have), per_length)
        if need > 0:
            extra = heuristic_clips(segments, L, need, exclude=taken)
            plans.extend(extra)
            taken.extend((p.start, p.end) for p in extra)
    return sorted(plans, key=lambda p: (p.target, p.start))
