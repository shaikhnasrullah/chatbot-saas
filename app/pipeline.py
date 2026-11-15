"""The full job: download -> transcribe -> choose clips -> translate -> edit -> render."""
import shutil
from pathlib import Path

from . import config
from .captions import build_srt, build_ass, chunk_words, phrases_from_words, spread_words
from .downloader import download
from .editor import (compute_keep_ranges, crop_width, crop_x_expr, extract_audio, plan_crop,
                     probe, remap_words, render_clip, total_len)
from .facetrack import sample_face_centers
from .highlights import pick_clips
from .languages import LANGUAGES


def _all_words(segments):
    words = []
    for s in segments:
        words.extend(s.words or spread_words(s.text, s.start, s.end))
    return words


def make_clip(src, info, plan, idx, words, req, src_lang, work_dir: Path, clips_dir: Path,
              music_path=None, translate_fn=None, dub_fn=None) -> dict:
    """Edit + render one clip. translate_fn / dub_fn are injectable for tests."""
    if translate_fn is None:
        from .translate import translate_texts as translate_fn
    if dub_fn is None:
        from .dub import build_dub_track as dub_fn

    cs, ce = plan.start, plan.end
    clip_words = [w for w in words if w.end > cs and w.start < ce]
    ranges = compute_keep_ranges(clip_words, cs, ce, req.remove_fillers, req.trim_silence)
    out_dur = total_len(ranges)
    out_words = remap_words(clip_words, ranges, drop_fillers=req.remove_fillers)

    vertical = req.vertical
    if vertical:
        out_w, out_h = 1080, 1920
    else:
        out_h = min(info["height"], 1080) // 2 * 2
        out_w = round(info["width"] * out_h / info["height"] / 2) * 2

    # ---- translation / dubbing text ----
    mode = req.caption_mode
    main_words, sub_words, title, dub_phrases = out_words, None, plan.title, None
    translating = bool(req.target_lang) and req.target_lang != src_lang
    if translating and (mode in ("translated", "both") or req.dub):
        phrases = phrases_from_words(out_words)
        tr = translate_fn([p.text for p in phrases] + [plan.title or ""], req.target_lang)
        tr_phrases, tr_title = tr[:-1], tr[-1]
        tr_words = []
        for ph, text in zip(phrases, tr_phrases):
            tr_words += spread_words(text, ph.start, ph.end)
        title = tr_title or plan.title
        if mode == "translated":
            main_words = tr_words
        elif mode == "both":
            main_words, sub_words = tr_words, out_words
        if req.dub:
            dub_texts = tr_phrases
            if req.target_lang == "hinglish":  # TTS reads Devanagari far better than Roman Hindi
                dub_texts = translate_fn([p.text for p in phrases], "hi")
            dub_phrases = [{"text": t, "start": p.start, "end": p.end} for p, t in zip(phrases, dub_texts)]

    # ---- captions (.ass burned in + .srt download) ----
    name = f"clip{idx:02d}_{plan.target}s"
    main_chunks = chunk_words(main_words, vertical) if mode != "none" else []
    sub_chunks = chunk_words(sub_words, vertical) if sub_words else None
    ass_name, srt_name = None, None
    if main_chunks or (req.show_title and title):
        ass = build_ass(out_w, out_h, main_chunks, sub_chunks,
                        title if req.show_title else None, vertical=vertical, font=config.CAPTION_FONT)
        ass_name = f"{name}.ass"
        (work_dir / ass_name).write_text(ass, encoding="utf-8")
    if main_chunks:
        srt_name = f"{name}.srt"
        (clips_dir / srt_name).write_text(build_srt(main_chunks), encoding="utf-8")

    # ---- vertical layout ----
    vmode, cw, expr = req.vertical_mode, None, None
    if vertical:
        cw = crop_width(info["height"])
        if cw >= info["width"]:
            vmode = "blur"  # source is already as narrow as 9:16
        elif vmode == "face":
            steps = plan_crop(sample_face_centers(src, cs, ce - cs), info["width"], cw)
            expr = crop_x_expr(steps)

    dub_wav = dub_fn(dub_phrases, req.target_lang, out_dur, work_dir, name=f"dub{idx:02d}") if dub_phrases else None
    fonts = config.CAPTION_FONTS_DIR if config.CAPTION_FONTS_DIR and Path(config.CAPTION_FONTS_DIR).is_dir() else None

    mp4_name = f"{name}.mp4"
    render_clip(
        src, str(clips_dir / mp4_name), cs, ce, ranges, work_dir,
        vertical=vertical, vmode=vmode, cw=cw, crop_expr=expr, ass_name=ass_name,
        has_audio=info["has_audio"], music=music_path, music_volume=req.music_volume,
        dub_wav=dub_wav, fontsdir=fonts,
    )
    return {
        "file": mp4_name, "srt": srt_name, "title": title, "reason": plan.reason,
        "score": plan.score, "target": plan.target, "source_start": round(cs, 1),
        "source_end": round(ce, 1), "duration": round(out_dur, 1),
    }


def run_pipeline(job_dir: Path, req, report, music_path=None):
    """report(progress=None, message=None, status=None, **extra)"""
    work, clips_dir = job_dir / "work", job_dir / "clips"
    work.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    report(3, "Video download ho raha hai…", status="downloading")
    src, meta = download(req.url, work, lambda f: report(3 + int(12 * f), "Video download ho raha hai…"))
    info = probe(src)
    report(15, "Audio transcribe ho raha hai…", status="transcribing", video_title=meta.get("title", ""))

    if not info["has_audio"]:
        raise RuntimeError("Is video mein audio nahi hai, isliye transcript nahi ban sakta.")
    from .transcriber import transcribe

    wav = work / "audio.wav"
    extract_audio(src, wav)
    segments, src_lang = transcribe(
        wav, req.source_lang, req.remove_fillers,
        lambda f: report(15 + int(35 * f), "Audio transcribe ho raha hai…"),
    )
    if not segments:
        raise RuntimeError("Video mein koi speech nahi mili.")

    report(50, "Best moments dhundh raha hoon…", status="selecting", detected_language=src_lang)
    title_lang = LANGUAGES[req.target_lang]["name"] if req.target_lang else "the transcript's language"
    plans = pick_clips(segments, info["duration"], req.lengths, req.per_length, title_lang)

    words = _all_words(segments)
    clips = []
    for i, plan in enumerate(plans, 1):
        report(55 + int(45 * (i - 1) / len(plans)), f"Clip {i}/{len(plans)} ban rahi hai…", status="rendering")
        clips.append(make_clip(src, info, plan, i, words, req, src_lang, work, clips_dir, music_path))
        report(clips=list(clips))

    if not config.KEEP_SOURCE:
        shutil.rmtree(work, ignore_errors=True)
    report(100, "Ho gaya!", status="done", clips=clips)
