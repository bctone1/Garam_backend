import grpc
import json
import pyaudio
import nest_pb2
import nest_pb2_grpc
from core import config
import base64
CLIENT_SECRET = config.CLOVA_STT_SECRET
CLIENT_ID = config.CLOVA_STT_ID

# 마이크 설정 (클로바 STT 요구사항: 16kHz, 16bit, mono)
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 32000  # 약 2초 분량 (16bit 샘플이라 1샘플=2바이트)

def generate_requests():
    # 초기 config 요청
    yield nest_pb2.NestRequest(
        type=nest_pb2.RequestType.CONFIG,
        config=nest_pb2.NestConfig(
            config=json.dumps({"transcription": {"language": "ko"}})
        )
    )

    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        frames_per_buffer=CHUNK // 2)  # CHUNK byte 기준이기에 2로 나눔

    print("Listening...")

    try:
        while True:
            data = stream.read(CHUNK // 2, exception_on_overflow=False)
            if not data:
                break
            yield nest_pb2.NestRequest(
                type=nest_pb2.RequestType.DATA,
                data=nest_pb2.NestData(
                    chunk=data,
                    extra_contents=json.dumps({"seqId": 0, "epFlag": False})
                )
            )
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()

def main():
    channel = grpc.secure_channel(
        "clovaspeech-gw.ncloud.com:50051",
        grpc.ssl_channel_credentials()
    )
    stub = nest_pb2_grpc.NestServiceStub(channel)
    auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    metadata = (("authorization", f"Basic {auth}"),)

    responses = stub.recognize(generate_requests(), metadata=metadata)

    try:
        for response in responses:
            print(responses)
            print("Received response:", response.contents)
    except grpc.RpcError as e:
        print(f"Error: {e.details()}")
    finally:
        channel.close()

