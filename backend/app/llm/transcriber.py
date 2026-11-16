import asyncio
import io
import math
from dataclasses import dataclass
from typing import Any, Protocol


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


class WhisperTranscriber:
    """Local speech-to-text with faster-whisper: no API key, nothing leaves the machine. The model
    downloads on first use and loads once; decoding runs in a thread so the worker stays live."""

    def __init__(self, model: str, device: str = "cpu", cache_dir: str = "") -> None:
        self._model_name, self._device, self._cache_dir = model, device, cache_dir
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel  # heavy import, only when a voice note arrives

            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type="int8",
                download_root=self._cache_dir or None,
            )
        return self._model

    def _run(self, audio: bytes) -> Transcription:
        segments, info = self._load().transcribe(io.BytesIO(audio), beam_size=1, vad_filter=True)
        parts = list(segments)  # a generator: decoding happens here
        text = " ".join(p.text.strip() for p in parts).strip()
        if not parts:
            return Transcription("", info.language, 0.0)
        # A heuristic, not a calibrated probability: the geometric mean token probability.
        confidence = math.exp(sum(p.avg_logprob for p in parts) / len(parts))
        return Transcription(text, info.language, max(0.0, min(1.0, confidence)))

    async def transcribe(self, audio: bytes, mime_type: str) -> Transcription:
        return await asyncio.to_thread(self._run, audio)
