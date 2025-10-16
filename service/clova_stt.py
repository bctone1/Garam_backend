import os
import io
import requests
import pyaudio
import wave
from dotenv import load_dotenv

# ─────────────────────────────
# ① 환경 변수 로드
# ─────────────────────────────
load_dotenv()
CLIENT_ID = os.getenv("CLOVA_STT_ID")
CLIENT_SECRET = os.getenv("CLOVA_STT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("❌ CLOVA_STT_ID 또는 CLOVA_STT_SECRET이 설정되지 않았습니다 (.env 확인).")

# ─────────────────────────────
# ② CSR API 설정
# ─────────────────────────────
LANG = "Kor"
CSR_URL = f"https://naveropenapi.apigw.ntruss.com/recog/v1/stt?lang={LANG}"

# ─────────────────────────────
# ③ 마이크 설정
# ─────────────────────────────
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 5  # 녹음 길이 (초)

def record_audio_to_bytes():
    """마이크로 녹음 후, WAV 포맷 바이트로 반환"""
    print("🎙 녹음 시작... (5초 동안 말하세요)")
    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT, channels=CHANNELS,
                        rate=RATE, input=True, frames_per_buffer=CHUNK)

    frames = []
    for _ in range(int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)

    print("✅ 녹음 완료")
    stream.stop_stream()
    stream.close()
    audio.terminate()

    # 메모리 버퍼에 WAV로 변환
    buffer = io.BytesIO()
    wf = wave.open(buffer, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(audio.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
    return buffer.getvalue()

def send_to_clova(audio_bytes: bytes):
    """CSR 서버로 음성 데이터 전송"""
    headers = {
        "X-NCP-APIGW-API-KEY-ID": CLIENT_ID,
        "X-NCP-APIGW-API-KEY": CLIENT_SECRET,
        "Content-Type": "application/octet-stream"
    }
    print("📤 CSR 서버로 전송 중...")
    response = requests.post(CSR_URL, headers=headers, data=audio_bytes)

    if response.status_code == 200:
        print("🗣 인식 결과:", response.json().get("text", "(결과 없음)"))
    else:
        print(f"❌ 오류 코드: {response.status_code}")
        print(response.text)

def main():
    audio_bytes = record_audio_to_bytes()
    send_to_clova(audio_bytes)

if __name__ == "__main__":
    main()
