import asyncio
import hashlib
import math
from typing import Any, Protocol

from app.db.base import EMBEDDING_DIM


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Deterministic hash-based unit vectors: same text, same vector. No model, no network."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [digest[i % len(digest)] - 127.5 for i in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


class LocalEmbedder:
    """fastembed (ONNX) on CPU: free, no API key, and the data never leaves the machine."""

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.dim = EMBEDDING_DIM
        self._model_name = model_name
        self._cache_dir = cache_dir or None
        self._model: Any = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_sync, texts)  # keep the event loop free

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from fastembed import (
                TextEmbedding,
            )  # imported late: it is slow and API does not need it

            self._model = TextEmbedding(self._model_name, cache_dir=self._cache_dir)
        vectors = [[float(x) for x in v] for v in self._model.embed(texts)]
        if vectors and len(vectors[0]) != self.dim:
            raise ValueError(
                f"embedding model returned {len(vectors[0])} dims, expected {self.dim}"
            )
        return vectors
