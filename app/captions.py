"""Caption building: phrases, word chunks, ASS (animated karaoke) and SRT output."""
import re

from .models import Phrase, Word

SENT_END = (".", "?", "!", "।", "。", "？", "！")
CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def is_cjk(text: str) -> bool:
    return bool(text) and len(CJK_RE.findall(text)) > len(text) * 0.3


def spread_words(text: str, start: float, end: float) -> list[Word]:
    """Give translated text word timings by spreading it over [start, end] by length."""
    text = text.strip()
    if not text or end <= start:
        return []
    if is_cjk(text):
        compact = text.replace(" ", "")
        tokens = [compact[i:i + 3] for i in range(0, len(compact), 3)]
    else:
        tokens = text.split()
    weights = [len(t) + 1 for t in tokens]
    total = float(sum(weights))
    words, t = [], start
    for tok, wgt in zip(tokens, weights):
        d = (end - start) * wgt / total
        words.append(Word(t, t + d, tok))
        t += d
    return words


def phrases_from_words(words: list[Word], max_words=14, max_gap=0.7) -> list[Phrase]:
    """Group words into sentence-like phrases (used as translation units)."""
    phrases, cur = [], []

    def flush():
        if cur:
            phrases.append(Phrase(" ".join(w.text for w in cur), cur[0].start, cur[-1].end))
            cur.clear()

    for w in words:
        if cur and (w.start - cur[-1].end > max_gap or len(cur) >= max_words):
            flush()
        cur.append(w)
        if w.text.endswith(SENT_END):
            flush()
    flush()
    return phrases


def chunk_words(words: list[Word], vertical=True) -> list[list[Word]]:
    max_words, max_chars = (4, 20) if vertical else (7, 36)
    chunks, cur = [], []
    for w in words:
        if cur:
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            gap = w.start - cur[-1].end
            if (len(cur) >= max_words or chars > max_chars or gap > 0.6
                    or cur[-1].text.endswith(SENT_END)):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


# ---------- ASS ----------

def ass_time(t: float) -> str:
    cs = max(0, int(round(t * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _events(chunks, style, layer, upper, karaoke, hold=0.2):
    events = []
    for i, ch in enumerate(chunks):
        st = ch[0].start
        en = ch[-1].end + hold
        if i + 1 < len(chunks):
            en = min(en, max(chunks[i + 1][0].start, ch[-1].end))
        if en <= st:
            en = st + 0.1
        if karaoke:
            parts = []
            for k, w in enumerate(ch):
                nxt = ch[k + 1].start if k + 1 < len(ch) else en
                cs = max(1, int(round((nxt - w.start) * 100)))
                txt = _esc(w.text.upper() if upper else w.text)
                parts.append(f"{{\\k{cs}}}{txt}")
            text = " ".join(parts)
        else:
            text = " ".join(_esc(w.text) for w in ch)
        events.append(f"Dialogue: {layer},{ass_time(st)},{ass_time(en)},{style},,0,0,0,,{text}")
    return events


def build_ass(width, height, main_chunks, sub_chunks=None, title=None, title_seconds=3.0,
              vertical=True, font="Arial") -> str:
    size = int(width * 0.072) if vertical else int(height * 0.06)
    size_sub = int(size * 0.55)
    size_title = int(size * 0.8)
    margin_v = int(height * (0.20 if vertical else 0.08))
    margin_v_sub = margin_v + int(size * 1.35)
    margin_h = int(width * 0.06)
    outline = max(3, int(size * 0.09))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H0000E5FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},0,2,{margin_h},{margin_h},{margin_v},1
Style: Sub,{font},{size_sub},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,{margin_h},{margin_h},{margin_v_sub},1
Style: Title,{font},{size_title},&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,0,0,3,{max(8, size // 5)},0,8,{margin_h},{margin_h},{int(height * 0.08)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    if title:
        events.append(
            f"Dialogue: 2,{ass_time(0)},{ass_time(title_seconds)},Title,,0,0,0,,{{\\fad(250,350)}}{_esc(title)}"
        )
    if sub_chunks:
        events += _events(sub_chunks, "Sub", 0, upper=False, karaoke=False)
    events += _events(main_chunks, "Default", 1, upper=True, karaoke=True)
    return header + "\n".join(events) + "\n"


# ---------- SRT ----------

def _srt_time(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(chunks: list[list[Word]]) -> str:
    out = []
    for i, ch in enumerate(chunks, 1):
        out.append(f"{i}\n{_srt_time(ch[0].start)} --> {_srt_time(ch[-1].end)}\n{' '.join(w.text for w in ch)}\n")
    return "\n".join(out)
