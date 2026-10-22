import hashlib
import math
from typing import Protocol


class Embedder(Protocol):
    dimension: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    def __init__(self, dimension: int = 1024) -> None:
        if dimension < 1:
            raise ValueError("Embedding dimension must be positive")
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.shake_256(text.encode()).digest(self.dimension * 2)
            vector = [
                int.from_bytes(digest[i : i + 2], "big") / 32768 - 1
                for i in range(0, len(digest), 2)
            ]
            norm = math.sqrt(sum(v * v for v in vector)) or 1
            vectors.append([v / norm for v in vector])
        return vectors


class Reranker(Protocol):
    async def rerank(self, query: str, documents: list[str]) -> list[str]: ...


class NoOpReranker:
    async def rerank(self, query: str, documents: list[str]) -> list[str]:
        return list(documents)
