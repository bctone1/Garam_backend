import tempfile, os, subprocess, io
import speech_recognition as sr

_rec = sr.Recognizer()

# def transcribe_bytes(data: bytes, content_type: str = "", lang: str = "ko-KR") -> str:
#     if content_type in {"audio/wav","audio/x-wav","audio/flac","audio/x-flac","audio/aiff","audio/x-aiff"}:
#         with sr.AudioFile(io.BytesIO(data)) as src:
#             audio = _rec.record(src)
#     else:
#         p = subprocess.run(
#             ["ffmpeg","-nostdin","-i","pipe:0","-f","s16le","-ac","1","-ar","16000","pipe:1"],
#             input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True
#         )
#         audio = sr.AudioData(p.stdout, 16000, 2)  # 16kHz, mono, 16-bit
#
#     text = _rec.recognize_google(audio, language=lang).strip()
#     if not text:
#         raise ValueError("empty transcription")
#     return text


def transcribe_bytes(data: bytes, content_type: str = "", lang: str = "ko-KR") -> str:
    with tempfile.NamedTemporaryFile(delete=False) as raw:
        raw.write(data); raw.flush()
        raw_path = raw.name
    try:
        if content_type in ("audio/wav", "audio/x-wav"):
            wav_path = raw_path
        else:
            wav_path = raw_path + ".wav"
            subprocess.run(
                ["ffmpeg", "-y", "-i", raw_path, "-ac", "1", "-ar", "16000", wav_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        with sr.AudioFile(wav_path) as src:
            audio = _rec.record(src)
        text = _rec.recognize_google(audio, language=lang).strip()
        if not text:
            raise ValueError("empty transcription")
        return text
    finally:
        for p in (locals().get("wav_path"), raw_path):
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass
