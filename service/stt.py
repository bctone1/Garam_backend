# service/stt.py
import tempfile, os, subprocess, io
import speech_recognition as sr
import wave, shutil, requests
from fastapi import HTTPException

_rec = sr.Recognizer()
CLOVA_STT_URL = os.getenv("CLOVA_STT_URL")

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


# Clova STT 전용 유틸
def _wav_duration_seconds(data: bytes) -> float:
    """WAV 파일 길이(초) 계산"""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 16000
            return max(0.0, frames / float(rate))
    except Exception:
        return 0.0


def _ensure_wav_16k_mono(data: bytes, content_type: str) -> bytes:
    """ffmpeg를 이용해 16kHz 모노 WAV로 변환"""
    if content_type in ("audio/wav", "audio/x-wav"):
        return data
    if not shutil.which("ffmpeg"):
        return data
    with tempfile.NamedTemporaryFile(delete=False) as raw:
        raw.write(data)
        raw.flush()
        wav_path = raw.name + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", raw.name, "-ac", "1", "-ar", "16000", wav_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        with open(wav_path, "rb") as f:
            return f.read()
    finally:
        for path in (raw.name, wav_path):
            try:
                os.remove(path)
            except:
                pass


def _clova_transcribe(data: bytes, lang: str) -> str:
    """Clova STT API 요청 및 결과 반환"""
    if not CLOVA_STT_URL:
        raise RuntimeError("CLOVA_STT_URL 미설정")
    cid = os.getenv("CLOVA_STT_ID")
    csec = os.getenv("CLOVA_STT_SECRET")
    if not cid or not csec:
        raise RuntimeError("CLOVA_STT_ID/CLOVA_STT_SECRET 미설정")

    headers = {
        "X-NCP-APIGW-API-KEY-ID": cid,
        "X-NCP-APIGW-API-KEY": csec,
        "Content-Type": "application/octet-stream",
    }
    url = f"{CLOVA_STT_URL}?lang={lang or 'ko-KR'}"
    r = requests.post(url, headers=headers, data=data, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"clova stt {r.status_code}: {r.text[:200]}")
    text = r.json().get("text", "").strip()
    if not text:
        raise ValueError("empty transcription")
    return text
