import os, io, wave
import pyaudio
from dotenv import load_dotenv
from openai import OpenAI

# ─────────────────────────────
# ① 환경 변수
# ─────────────────────────────
load_dotenv()
API_KEY = os.getenv("OPENAI_API")
LANG = "ko"
DURATION = int(os.getenv("DURATION", "5"))

if not API_KEY:
    raise ValueError("OPENAI_API_KEY가 필요합니다 ")

# ─────────────────────────────
# ② 마이크 설정
# ─────────────────────────────
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024

def record_audio_to_wav_bytes(seconds: int = 5) -> bytes:
    """마이크로 녹음 후 WAV 바이트 반환(16k/mono/16bit)"""
    pa = pyaudio.PyAudio()
    stream = pa.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                     input=True, frames_per_buffer=CHUNK)
    print(f"🎙 녹음 시작... ({seconds}초)")
    frames = []
    for _ in range(int(RATE / CHUNK * seconds)):
        frames.append(stream.read(CHUNK, exception_on_overflow=False))
    print("✅ 녹음 완료")

    stream.stop_stream(); stream.close(); pa.terminate()

    buf = io.BytesIO()
    wf = wave.open(buf, "wb")
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(pa.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b"".join(frames))
    wf.close()
    return buf.getvalue()

# ─────────────────────────────
# ③ Whisper API 호출
# ─────────────────────────────
def transcribe_with_whisper(wav_bytes: bytes, *, language: str = "ko") -> str:
    client = OpenAI(api_key=API_KEY)
    # file-like 객체로 전달
    file_like = io.BytesIO(wav_bytes)
    file_like.name = "audio.wav"  # 확장자 힌트
    resp = client.audio.transcriptions.create(
        # model="whisper-1", 
        model="large-v3-turbo",
        file=file_like,
        language=language,     # 언어 고정. 자동 감지 원하면 제거
        response_format="json" # 기본값
    )
    return resp.text.strip()


## 마이크 테스트 용도
def main():
    audio_bytes = record_audio_to_wav_bytes(DURATION)
    text = transcribe_with_whisper(audio_bytes, language=LANG)
    print("🗣 인식 결과:", text or "(비어있음)")

if __name__ == "__main__":
    main()
