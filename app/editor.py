"""Video editing with ffmpeg: cut, filler/silence removal, vertical crop, music, captions."""
import json
import re
from pathlib import Path

from .models import Word
from .utils import even, run

FILLERS = {
    "um", "umm", "uh", "uhh", "erm", "er", "ah", "ahh", "hmm", "hm", "mm", "mmm", "eh",
    "uhm", "huh",
}


def is_filler(text: str) -> bool:
    return re.sub(r"[^\w']", "", text.lower()) in FILLERS


# ---------- probing / audio ----------

def probe(path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    return {
        "duration": float(d["format"]["duration"]),
        "width": int(v["width"]),
        "height": int(v["height"]),
        "has_audio": any(s["codec_type"] == "audio" for s in d["streams"]),
    }


def extract_audio(src, out_wav):
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", "1",
         "-ar", "16000", "-c:a", "pcm_s16le", out_wav])


# ---------- timeline: filler words and silence ----------

def compute_keep_ranges(words, cs, ce, remove_fillers=True, trim_silence=True,
                        silence_thr=0.7, keep_gap=0.2, lead=0.25, tail=0.4):
    """Return the absolute (start, end) ranges of [cs, ce] to KEEP."""
    ws = [w for w in words if w.end > cs and w.start < ce]
    if not ws or not (remove_fillers or trim_silence):
        return [(cs, ce)]

    cuts = []
    if trim_silence:
        lead_end = max(cs, ws[0].start - lead)
        if lead_end > cs + 0.05:
            cuts.append((cs, lead_end))
        tail_start = min(ce, ws[-1].end + tail)
        if ce - tail_start > 0.05:
            cuts.append((tail_start, ce))
        for a, b in zip(ws, ws[1:]):
            if b.start - a.end > silence_thr:
                cuts.append((a.end + keep_gap, b.start - keep_gap))
    if remove_fillers:
        for w in ws:
            if is_filler(w.text) and w.end - w.start >= 0.12:
                cuts.append((max(cs, w.start + 0.02), min(ce, w.end - 0.02)))

    cuts.sort()
    merged = []
    for s, e in cuts:
        if e <= s:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    keep, pos = [], cs
    for s, e in merged:
        if s - pos >= 0.15:
            keep.append((pos, s))
        pos = max(pos, e)
    if ce - pos >= 0.15:
        keep.append((pos, ce))
    return keep or [(cs, ce)]


def total_len(ranges) -> float:
    return sum(e - s for s, e in ranges)


def remap_time(t, ranges) -> float:
    """Map an absolute source time to the output timeline (cut regions snap forward)."""
    acc = 0.0
    for s, e in ranges:
        if t < s:
            return acc
        if t <= e:
            return acc + (t - s)
        acc += e - s
    return acc


def remap_words(words, ranges, drop_fillers=True) -> list[Word]:
    """Words that survive the edit, with timings on the output timeline."""
    out = []
    for w in words:
        if drop_fillers and is_filler(w.text):
            continue
        mid = (w.start + w.end) / 2
        if not any(s <= mid <= e for s, e in ranges):
            continue
        ns, ne = remap_time(w.start, ranges), remap_time(w.end, ranges)
        if out and ns < out[-1].end:
            ns = out[-1].end
        if ne <= ns:
            ne = ns + 0.05
        out.append(Word(ns, ne, w.text))
    return out


# ---------- vertical crop planning ----------

def plan_crop(samples, src_w, cw, threshold=0.18, min_hold=1.0):
    """samples: [(t, face_center_x or None)] -> [(t, crop_x)] piecewise-constant steps."""
    max_x = src_w - cw
    if max_x <= 0:
        return [(0.0, 0.0)]
    valid = [c for _, c in samples if c is not None]
    if not valid:
        return [(0.0, max_x / 2)]

    filled, last = [], valid[0]
    for t, c in samples:
        if c is None:
            c = last
        last = c
        filled.append((t, c))

    # median smoothing (window 5) to ignore single-frame detection jumps
    centers = [c for _, c in filled]
    smooth = []
    for i in range(len(centers)):
        win = sorted(centers[max(0, i - 2): i + 3])
        smooth.append(win[len(win) // 2])

    def to_x(c):
        return min(max(c - cw / 2, 0.0), max_x)

    steps = [(0.0, to_x(smooth[0]))]
    for (t, _), c in zip(filled, smooth):
        x = to_x(c)
        if abs(x - steps[-1][1]) > threshold * cw and t - steps[-1][0] >= min_hold:
            steps.append((t, x))
    return steps


def crop_x_expr(steps, ramp=0.5) -> str:
    """ffmpeg expression for crop x(t) that eases between the steps."""
    terms = [f"{steps[0][1]:.1f}"]
    for (t, x), (_, px) in zip(steps[1:], steps):
        terms.append(f"clip((t-{t:.2f})/{ramp},0,1)*({x - px:.1f})")
    return "+".join(terms)


# ---------- filter graph + render ----------

def build_graph(rel_ranges, out_dur, vertical, vmode, cw, crop_expr, ass_name, has_audio,
                music_idx=None, music_volume=0.12, dub_idx=None, dub_bg_volume=0.12,
                fontsdir=None) -> str:
    g = []

    # 1) layout
    if vertical and vmode == "face" and cw:
        g.append(f"[0:v]crop=w={cw}:h=ih:x='{crop_expr}':y=0,scale=1080:1920:flags=lanczos,setsar=1[vb]")
    elif vertical:
        g.append(
            "[0:v]split=2[bg0][fg0];"
            "[bg0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bgb];"
            "[fg0]scale=1080:1920:force_original_aspect_ratio=decrease[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[vb]"
        )
    else:
        g.append("[0:v]scale=-2:'min(ih,1080)',setsar=1[vb]")

    # 2) cut the kept ranges and join them (this is where fillers / silence disappear)
    n = len(rel_ranges)
    if n > 1:
        g.append("[vb]split=%d%s" % (n, "".join(f"[vs{i}]" for i in range(n))))
        if has_audio:
            g.append("[0:a]asplit=%d%s" % (n, "".join(f"[as{i}]" for i in range(n))))
    for i, (s, e) in enumerate(rel_ranges):
        vin = f"[vs{i}]" if n > 1 else "[vb]"
        g.append(f"{vin}trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[vt{i}]")
        if has_audio:
            ain = f"[as{i}]" if n > 1 else "[0:a]"
            g.append(f"{ain}atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[at{i}]")
    if has_audio:
        pairs = "".join(f"[vt{i}][at{i}]" for i in range(n))
        g.append(f"{pairs}concat=n={n}:v=1:a=1[vc][ac]")
    else:
        pairs = "".join(f"[vt{i}]" for i in range(n))
        g.append(f"{pairs}concat=n={n}:v=1:a=0[vc]")
        g.append(f"anullsrc=r=44100:cl=stereo,atrim=duration={out_dur:.3f}[ac]")

    # 3) captions
    if ass_name:
        sub = f"ass={ass_name}" + (f":fontsdir={fontsdir}" if fontsdir else "")
        g.append(f"[vc]{sub},format=yuv420p[vout]")
    else:
        g.append("[vc]format=yuv420p[vout]")

    # 4) audio: optional dub, optional music, loudness normalisation
    cur = "ac"
    if dub_idx is not None:
        g.append(f"[{cur}]volume={dub_bg_volume:.3f}[bg]")
        g.append(f"[{dub_idx}:a]aresample=44100[dv]")
        g.append("[bg][dv]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a1]")
        cur = "a1"
    if music_idx is not None:
        g.append(f"[{music_idx}:a]volume={music_volume:.3f},atrim=duration={out_dur:.3f},asetpts=PTS-STARTPTS[mus]")
        g.append(f"[{cur}][mus]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a2]")
        cur = "a2"
    g.append(f"[{cur}]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100[aout]")
    return ";".join(g)


def render_clip(src, out, cs, ce, ranges, work_dir, *, vertical, vmode, cw=None, crop_expr=None,
                ass_name=None, has_audio=True, music=None, music_volume=0.12, dub_wav=None,
                fontsdir=None):
    """Render one finished clip. `ranges` are absolute source ranges to keep."""
    rel = [(s - cs, e - cs) for s, e in ranges]
    out_dur = total_len(ranges)

    inputs, idx = [], 1
    music_idx = dub_idx = None
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        music_idx, idx = idx, idx + 1
    if dub_wav:
        inputs += ["-i", dub_wav]
        dub_idx, idx = idx, idx + 1

    graph = build_graph(rel, out_dur, vertical, vmode, cw, crop_expr, ass_name, has_audio,
                        music_idx, music_volume, dub_idx, fontsdir=fontsdir)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{cs:.3f}", "-t", f"{ce - cs:.3f}", "-i", src, *inputs,
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        "-t", f"{out_dur:.3f}", out,
    ]
    run(cmd, cwd=work_dir)
    return out_dur


def crop_width(src_h: int) -> int:
    """Width of a 9:16 crop taken from a source of height src_h."""
    return even(src_h * 9 / 16)
