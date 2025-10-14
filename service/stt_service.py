from typing import Optional

class STTService:
    def __init__(self, provider: str, **kwargs):
        self.provider = provider
        self.kwargs = kwargs

    def transcribe(self, wav_path: str, *, language: Optional[str]=None) -> str:
        # TODO: Whisper/ Web speech/ clova
        return "recognized text"
