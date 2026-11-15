from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str  # e.g. "hi", "gu", "en"
    confidence: float  # 0-1; below a threshold the bot asks the customer to confirm or type


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str) -> Transcription: ...


class FakeTranscriber:
    """Returns scripted transcriptions in order. Tests never run a speech model."""

    def __init__(self, results: list[Transcription]) -> None:
        self._results = list(results)
        self.calls = 0

    async def transcribe(self, audio: bytes, mime_type: str) -> Transcription:
        self.calls += 1
        return self._results.pop(0)
