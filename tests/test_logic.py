"""Unit tests for the pure logic (no network, no models). Run: python -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import highlights, llm, translate  # noqa: E402
from app.captions import (build_ass, build_srt, chunk_words, phrases_from_words,  # noqa: E402
                          spread_words, ass_time)
from app.editor import (build_graph, compute_keep_ranges, crop_x_expr, plan_crop,  # noqa: E402
                        remap_time, remap_words)
from app.models import Segment, Word  # noqa: E402


def W(start, end, text):
    return Word(start, end, text)


def make_segments(n=60, seg_len=6.0):
    segs = []
    for i in range(n):
        s = i * seg_len
        text = f"This is sentence number {i} about money and the biggest mistake ever?" if i % 7 == 0 else f"Plain sentence {i}."
        segs.append(Segment(s, s + seg_len - 0.2, text))
    return segs


class KeepRanges(unittest.TestCase):
    def test_no_edit_keeps_everything(self):
        self.assertEqual(compute_keep_ranges([W(1, 2, "hi")], 0, 10, False, False), [(0, 10)])

    def test_filler_is_cut(self):
        words = [W(0.5, 1.0, "hello"), W(1.0, 1.6, "um"), W(1.6, 2.2, "world")]
        keep = compute_keep_ranges(words, 0, 3, remove_fillers=True, trim_silence=False)
        self.assertEqual(len(keep), 2)
        self.assertLess(keep[0][1], 1.1)
        self.assertGreater(keep[1][0], 1.5)

    def test_long_silence_is_shortened(self):
        words = [W(0.3, 1.0, "a"), W(4.0, 4.5, "b")]
        keep = compute_keep_ranges(words, 0, 5, remove_fillers=False, trim_silence=True)
        total = sum(e - s for s, e in keep)
        self.assertLess(total, 3.0)  # 5s clip minus ~2.6s of dead air and lead/tail trims

    def test_remap_time_and_words(self):
        keep = [(0, 2), (4, 6)]
        self.assertAlmostEqual(remap_time(1, keep), 1)
        self.assertAlmostEqual(remap_time(5, keep), 3)
        self.assertAlmostEqual(remap_time(3, keep), 2)  # inside a cut -> snaps to the next kept start
        words = [W(0.5, 1.0, "hi"), W(2.5, 3.5, "gone"), W(4.5, 5.0, "bye"), W(5.0, 5.4, "uh")]
        out = remap_words(words, keep, drop_fillers=True)
        self.assertEqual([w.text for w in out], ["hi", "bye"])
        self.assertAlmostEqual(out[1].start, 2.5)


class Captions(unittest.TestCase):
    def test_spread_words_covers_span(self):
        ws = spread_words("yeh bahut zaroori baat hai", 10.0, 12.0)
        self.assertEqual(len(ws), 5)
        self.assertAlmostEqual(ws[0].start, 10.0)
        self.assertAlmostEqual(ws[-1].end, 12.0)

    def test_spread_words_cjk(self):
        ws = spread_words("这是一个很重要的问题", 0, 3)
        self.assertGreater(len(ws), 1)

    def test_phrases_split_on_sentence_end(self):
        words = [W(0, .3, "Hello"), W(.3, .6, "there."), W(.7, 1, "Next"), W(1, 1.3, "one")]
        ph = phrases_from_words(words)
        self.assertEqual([p.text for p in ph], ["Hello there.", "Next one"])

    def test_chunks_respect_limits(self):
        words = [W(i * .3, i * .3 + .25, "word") for i in range(10)]
        chunks = chunk_words(words, vertical=True)
        self.assertTrue(all(len(c) <= 4 for c in chunks))
        self.assertEqual(sum(len(c) for c in chunks), 10)

    def test_ass_and_srt(self):
        words = [W(0.0, 0.4, "Hello"), W(0.4, 0.8, "नमस्ते"), W(0.9, 1.3, "world")]
        chunks = chunk_words(words)
        ass = build_ass(1080, 1920, chunks, sub_chunks=chunks, title="My {Title}")
        self.assertIn("PlayResY: 1920", ass)
        self.assertIn("Dialogue: 1,0:00:00.00", ass)
        self.assertIn("{\\k", ass)
        self.assertIn("नमस्ते", ass)
        self.assertNotIn("{Title}", ass)  # braces would break ASS override parsing
        srt = build_srt(chunks)
        self.assertIn("00:00:00,000 --> 00:00:01,300", srt)
        self.assertEqual(ass_time(3661.5), "1:01:01.50")


class Crop(unittest.TestCase):
    def test_center_when_no_faces(self):
        steps = plan_crop([(0, None), (.5, None)], 1280, 404)
        self.assertEqual(len(steps), 1)
        self.assertAlmostEqual(steps[0][1], (1280 - 404) / 2)

    def test_follows_speaker_who_moves(self):
        samples = [(t * .5, 300.0 if t < 8 else 1000.0) for t in range(16)]
        steps = plan_crop(samples, 1280, 404)
        self.assertGreaterEqual(len(steps), 2)
        self.assertLessEqual(steps[-1][1], 1280 - 404)
        expr = crop_x_expr(steps)
        self.assertIn("clip((t-", expr)


class Selection(unittest.TestCase):
    def test_parse_json_block(self):
        self.assertEqual(highlights.parse_json_block('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(highlights.parse_json_block('Sure! {"a": [1, 2]} done'), {"a": [1, 2]})
        with self.assertRaises(ValueError):
            highlights.parse_json_block("no json here")

    def test_heuristic_picks_are_non_overlapping_and_sized(self):
        segs = make_segments()
        picks = highlights.heuristic_clips(segs, 60, 3)
        self.assertEqual(len(picks), 3)
        for a in picks:
            self.assertTrue(0.8 * 60 <= a.end - a.start <= 1.25 * 60)
        spans = sorted((p.start, p.end) for p in picks)
        self.assertTrue(all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1)))

    def test_finalize_snaps_and_drops_bad_clips(self):
        segs = make_segments()
        raw = [
            {"target": 60, "start": 13.0, "end": 71.0, "title": "Good", "score": 9},
            {"target": 60, "start": 20.0, "end": 30.0, "title": "Too short", "score": 5},
            {"target": 120, "start": 120.0, "end": 240.0, "title": "Long", "score": 7},
            {"target": 60, "start": 15.0, "end": 75.0, "title": "Overlaps first", "score": 3},
            {"bad": "row"},
        ]
        plans = highlights.finalize(raw, segs, 360.0, [60, 120])
        titles = [p.title for p in plans]
        self.assertIn("Good", titles)
        self.assertIn("Long", titles)
        self.assertNotIn("Too short", titles)
        self.assertNotIn("Overlaps first", titles)
        starts = {s.start for s in segs}
        self.assertTrue(all(p.start in starts for p in plans))

    def test_pick_clips_without_llm_uses_heuristic(self):
        segs = make_segments(n=80)
        orig = llm.available
        llm.available = lambda: False
        try:
            plans = highlights.pick_clips(segs, 480.0, [60, 120], 2)
        finally:
            llm.available = orig
        self.assertEqual(len([p for p in plans if p.target == 60]), 2)
        self.assertEqual(len([p for p in plans if p.target == 120]), 2)

    def test_pick_clips_short_video_returns_whole(self):
        segs = make_segments(n=3)
        plans = highlights.pick_clips(segs, 18.0, [60, 120], 2)
        self.assertEqual(len(plans), 1)


class Translate(unittest.TestCase):
    def test_batches_and_recovers_from_count_mismatch(self):
        calls = []

        def fake(system, user, max_tokens=4000):
            lines = [l.split(". ", 1)[1] for l in user.splitlines()]
            calls.append(len(lines))
            if len(lines) == 4:  # first attempt returns the wrong count -> must split & retry
                return '["only one"]'
            return "[" + ",".join(f'"T:{l}"' for l in lines) + "]"

        orig = llm.complete
        llm.complete = fake
        try:
            out = translate.translate_texts(["a", "b", "c", "d"], "hi")
        finally:
            llm.complete = orig
        self.assertEqual(out, ["T:a", "T:b", "T:c", "T:d"])
        self.assertEqual(calls[0], 4)


class Graph(unittest.TestCase):
    def test_graph_labels_balanced(self):
        g = build_graph([(0, 3), (4, 8)], 7.0, True, "face", 404, "200+0", "c.ass", True,
                        music_idx=1, dub_idx=2)
        for label in ("[vout]", "[aout]", "concat=n=2", "amix", "loudnorm", "ass=c.ass"):
            self.assertIn(label, g)


if __name__ == "__main__":
    unittest.main()
