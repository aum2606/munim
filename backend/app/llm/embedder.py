import hashlib
import math
from typing import Protocol


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Deterministic hash-based unit vectors: same text, same vector. No model, no network."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [digest[i % len(digest)] - 127.5 for i in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]
