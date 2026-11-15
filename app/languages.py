"""Languages offered for translation / dubbing, with an edge-tts voice for each.

Voices can be changed freely: run `edge-tts --list-voices` to see all available names.
"""

LANGUAGES = {
    "en": {"name": "English", "voice": "en-US-AriaNeural"},
    "hi": {"name": "Hindi (हिन्दी)", "voice": "hi-IN-SwaraNeural"},
    "hinglish": {"name": "Hinglish (Hindi in Roman script)", "voice": "hi-IN-SwaraNeural"},
    "bn": {"name": "Bengali", "voice": "bn-IN-TanishaaNeural"},
    "ta": {"name": "Tamil", "voice": "ta-IN-PallaviNeural"},
    "te": {"name": "Telugu", "voice": "te-IN-ShrutiNeural"},
    "mr": {"name": "Marathi", "voice": "mr-IN-AarohiNeural"},
    "gu": {"name": "Gujarati", "voice": "gu-IN-DhwaniNeural"},
    "ur": {"name": "Urdu", "voice": "ur-IN-GulNeural"},
    "es": {"name": "Spanish", "voice": "es-ES-ElviraNeural"},
    "fr": {"name": "French", "voice": "fr-FR-DeniseNeural"},
    "de": {"name": "German", "voice": "de-DE-KatjaNeural"},
    "pt": {"name": "Portuguese", "voice": "pt-BR-FranciscaNeural"},
    "ar": {"name": "Arabic", "voice": "ar-SA-ZariyahNeural"},
    "ja": {"name": "Japanese", "voice": "ja-JP-NanamiNeural"},
    "ko": {"name": "Korean", "voice": "ko-KR-SunHiNeural"},
    "zh": {"name": "Chinese", "voice": "zh-CN-XiaoxiaoNeural"},
    "ru": {"name": "Russian", "voice": "ru-RU-SvetlanaNeural"},
    "id": {"name": "Indonesian", "voice": "id-ID-GadisNeural"},
    "tr": {"name": "Turkish", "voice": "tr-TR-EmelNeural"},
}
