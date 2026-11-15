# ✂️ Clipper — YouTube link se 1-min / 2-min clips

YouTube link paste karo → website best moments dhundhti hai → captions, translation aur editing ke saath finished clips deti hai (OpusClip jaisa).

## Features

| Feature | Kaise hota hai |
|---|---|
| Video download | `yt-dlp` (max 1080p) |
| Transcription + word timestamps | `faster-whisper` (local, free) |
| Best 1 min / 2 min clips | Claude hook + complete thought wale segments chunta hai; API key na ho to local heuristic fallback |
| Animated captions | Word-by-word highlight (gold = bola ja chuka word), `.ass` ffmpeg se video par burn, saath mein `.srt` download |
| Translation | Claude se (Hindi, Hinglish, Tamil, Telugu, Bengali, Marathi, Gujarati, Urdu, Spanish, French, German, Japanese, Korean, Chinese, Arabic …) |
| Caption modes | Original / Translated / Dono (translated bada + original chhota) / Koi nahi |
| AI dubbing | Translated text ko `edge-tts` se bulwa kar clip mein mix (original awaaz dheemi) |
| Vertical 9:16 | Face-tracking crop **ya** blur-background (poori video dikhe) **ya** original 16:9 |
| Filler words hatana | "umm", "uh", "hmm" cut ho jate hain (English source language chuno to best) |
| Silence trim | Lambi pauses chhoti, shuruaat/ant ki khaali jagah kati |
| Title hook | Pehle 3 second mein clip ka title |
| Background music | `music/` folder ki mp3, volume slider |
| Loudness | Har clip -16 LUFS par normalise |

## Setup (Windows / Mac / Linux)

1. **Python 3.10+** aur **ffmpeg** install karo (`ffmpeg -version` chalna chahiye)
   - Windows: `winget install ffmpeg` · Mac: `brew install ffmpeg` · Ubuntu: `sudo apt install ffmpeg`
2. Project folder mein:
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env            # Windows: copy .env.example .env
   ```
3. `.env` mein `ANTHROPIC_API_KEY=` bharo (https://console.anthropic.com). Iske bina clips local heuristic se chunte hain aur translation/dubbing band rehti hai.
4. (Optional) Background music ke liye `music/` folder mein mp3 daalo.
5. Pehle ek sanity check (sirf ffmpeg chahiye, internet nahi):
   ```bash
   python tests/smoke_render.py
   ```
   Chaaron lines `OK` dikhni chahiye.
6. Server chalao:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   Browser mein `http://localhost:8000` kholo, link paste karo, **Clips banao** dabao.

Pehli baar Whisper model download hoga (`small` ≈ 500 MB). CPU par 10 min ki video ~3–6 min leti hai; GPU (`WHISPER_DEVICE=cuda`) par bahut tez.

## Folder structure

```
app/
  main.py         FastAPI: /api/jobs, /api/config, clip download
  pipeline.py     poora flow (download → transcribe → select → edit → render)
  downloader.py   yt-dlp
  transcriber.py  faster-whisper
  highlights.py   Claude clip selection + heuristic fallback
  translate.py    Claude translation
  captions.py     phrases, chunks, ASS (animated) + SRT
  editor.py       ffmpeg: cut, filler/silence removal, crop, music, loudnorm
  facetrack.py    OpenCV face tracking for 9:16 crop
  dub.py          edge-tts dubbing track
  config.py / languages.py / llm.py / models.py / utils.py
static/index.html frontend
tests/            unit tests + smoke_render.py
data/jobs/<id>/   har job ka output (clips/*.mp4, *.srt)
```

## Tests

```bash
python -m unittest discover -s tests -v   # logic tests (bina internet)
python tests/smoke_render.py              # real ffmpeg rendering
```

## Troubleshooting

- **"Sign in to confirm you're not a bot" / download fail**: `pip install -U yt-dlp`, aur browser se `cookies.txt` export karke `.env` mein `YTDLP_COOKIES=cookies.txt`.
- **Hindi/Tamil captions ke dabbe (□□) dikhen**: koi Unicode font install karo (jaise *Noto Sans Devanagari*) aur `.env` mein `CAPTION_FONT=Noto Sans Devanagari`. Ya `.ttf` files ek folder mein rakh kar `CAPTION_FONTS_DIR=fonts`.
- **Face crop center hi rehta hai**: OpenCV mein face model file na ho to center crop par fall back hota hai. `opencv-python-headless` install karne se file milti hai.
- **Dubbing ki awaaz galat language/voice**: `app/languages.py` mein voice naam badlo (`edge-tts --list-voices`).
- **Translation ya clip selection fail**: `.env` ki API key aur model naam (`CLAUDE_MODEL`) check karo. Selection fail hone par app khud local heuristic use karti hai.

## Production ke liye aage kya

- Abhi jobs ek in-process queue mein chalte hain (`WORKERS=1`). Zyada users ke liye Celery + Redis lagao.
- Login aur clips ka record Firebase mein rakh sakte ho (FRALEN wala setup).
- GPU wale server par deploy karo; Whisper aur ffmpeg heavy hain, free hosting par fail ya slow honge.
- `data/jobs/` ko cron se purane jobs hata kar saaf rakho.

## ⚠️ Copyright / Terms

Sirf **apne videos** ya jin videos ki **permission** ho unhi ke clips banao. Doosron ke YouTube videos download karke clips banana YouTube ki Terms of Service ke khilaf ho sakta hai aur copyright ka issue banta hai. Public website banao to yeh disclaimer rakho aur ho sake to Google Sign-in se user ko sirf apne channel ke videos tak limit karo.
