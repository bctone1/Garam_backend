# service/stt.py
from __future__ import annotations

import os
import subprocess
import tempfile
import wave
from typing import Optional

import requests


def ensure_wav_16k_mono(data: bytes, content_type: str) -> bytes:
    """
    입력 오디오(bytes)를 ffmpeg로 wav(16kHz/mono)로 변환해서 bytes로 반환.
    ffmpeg 미설치/실패 시 RuntimeError.
    """
    in_name: Optional[str] = None
    out_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as f_in:
            in_name = f_in.name
            f_in.write(data)
            f_in.flush()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f_out:
            out_name = f_out.name

        # 항상 변환(입력 포맷 다양성 대응)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            in_name,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            out_name,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)

        out = open(out_name, "rb").read()
        if not out:
            raise RuntimeError("ffmpeg produced empty output")
        return out
    except Exception as e:
        raise RuntimeError(f"audio convert failed: {e}") from e
    finally:
        for p in (in_name, out_name):
            if p:
                try:
                    os.remove(p)
                except Exception:
                    pass


def wav_duration_seconds(wav_bytes: bytes) -> float:
    """
    wav header 기반 길이 추출. 실패 시 0.
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            name = f.name
            f.write(wav_bytes)
            f.flush()

        with wave.open(name, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0:
                return 0.0
            return float(frames) / float(rate)
    except Exception:
        return 0.0
    finally:
        try:
            os.remove(name)
        except Exception:
            pass


def probe_duration_seconds(data: bytes) -> float:
    """
    ffprobe로 길이 추출(비-wav fallback). 실패 시 0.
    """
    tmp_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(data)
            tmp.flush()

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                tmp_name,
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        secs = float((result.stdout or "").strip() or "0")
        return max(0.0, secs)
    except Exception:
        return 0.0
    finally:
        if tmp_name:
            try:
                os.remove(tmp_name)
            except Exception:
                pass


def clova_transcribe(wav_16k_mono: bytes, lang: str) -> str:
    """
    CLOVA STT 호출. 환경변수:
    - CLOVA_STT_URL
    - CLOVA_STT_API_KEY_ID
    - CLOVA_STT_API_KEY
    """
    url = os.getenv("CLOVA_STT_URL")
    key_id = os.getenv("CLOVA_STT_API_KEY_ID")
    key = os.getenv("CLOVA_STT_API_KEY")
    if not url or not key_id or not key:
        raise RuntimeError("CLOVA STT env missing: CLOVA_STT_URL / CLOVA_STT_API_KEY_ID / CLOVA_STT_API_KEY")

    headers = {
        "Content-Type": "application/octet-stream",
        "X-NCP-APIGW-API-KEY-ID": key_id,
        "X-NCP-APIGW-API-KEY": key,
    }

    # URL에 lang 파라미터가 이미 포함된 형태도 있어서, 둘 다 안전하게 처리
    params = {}
    if "lang=" not in url:
        params["lang"] = lang

    r = requests.post(url, headers=headers, params=params, data=wav_16k_mono, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"clova stt http {r.status_code}: {r.text}")

    # 보통 {"text": "..."} 형태
    try:
        j = r.json()
        return str(j.get("text") or j.get("result") or "")
    except Exception:
        # 혹시 plain text로 오는 경우
        return (r.text or "").strip()
