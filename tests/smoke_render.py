"""End-to-end render test with a synthetic video (needs only ffmpeg + OpenCV).

Checks that ffmpeg/libass work on your machine and that every editing path renders:
face-crop, blur layout, horizontal, filler/silence cuts, captions, translation (faked),
dub track (faked) and background music.   Run: python tests/smoke_render.py
"""
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.editor import probe  # noqa: E402
from app.models import ClipPlan, Word  # noqa: E402
from app.pipeline import make_clip  # noqa: E402
from app.utils import run  # noqa: E402


def fake_words():
    words, t = [], 0.5
    script = "Hello everyone um welcome back to the channel today we will talk about a big mistake uh people make".split()
    for i, txt in enumerate(script):
        d = 0.35 if txt not in ("um", "uh") else 0.4
        words.append(Word(t, t + d, txt + ("." if i == 7 else "")))
        t += d + 0.05
        if i == 9:
            t += 2.0  # a long silence in the middle
    return words


def fake_translate(texts, lang):
    return [f"अनुवाद {t}" for t in texts]


def fake_dub(phrases, lang, dur, work_dir, name="dub"):
    out = Path(work_dir) / f"{name}.wav"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         f"sine=frequency=300:duration={dur:.2f}", "-ac", "1", "-ar", "24000", out])
    return out


def main():
    tmp = Path(tempfile.mkdtemp(prefix="clipper_smoke_"))
    work, clips = tmp / "work", tmp / "clips"
    work.mkdir()
    clips.mkdir()
    src = tmp / "source.mp4"
    music = tmp / "music.mp3"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=20",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", src])
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=220:duration=5", music])

    info = probe(src)
    words = fake_words()
    plan = ClipPlan(0.0, 19.0, "Ek bada mistake", "test", 8, 60)
    base = dict(vertical=True, vertical_mode="face", remove_fillers=True, trim_silence=True,
                caption_mode="original", target_lang=None, dub=False, show_title=True,
                music_volume=0.12)
    cases = {
        "vertical_face_cuts_music": (dict(), str(music)),
        "vertical_blur": (dict(vertical_mode="blur"), None),
        "horizontal_no_captions": (dict(vertical=False, caption_mode="none", show_title=False), None),
        "translated_both_dub": (dict(target_lang="hi", caption_mode="both", dub=True), str(music)),
    }
    ok = True
    for i, (name, (over, mus)) in enumerate(cases.items(), 1):
        req = SimpleNamespace(**{**base, **over})
        res = make_clip(src, info, plan, i, words, req, "en", work, clips, mus,
                        translate_fn=fake_translate, dub_fn=fake_dub)
        out_info = probe(clips / res["file"])
        good = out_info["has_audio"] and abs(out_info["duration"] - res["duration"]) < 0.6
        print(f"{'OK  ' if good else 'FAIL'} {name:28s} {out_info['width']}x{out_info['height']} "
              f"{out_info['duration']:.1f}s (planned {res['duration']}s, source window 19s)")
        ok &= good
    if "--keep" in sys.argv:
        print(f"Output kept in: {clips}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
