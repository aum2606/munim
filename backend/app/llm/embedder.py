import hashlib
import math
from typing import Protocol

import httpx

from app.core.config import Settings


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


class OpenAICompatibleEmbedder:
    """https://developers.openai.com/api/reference/resources/embeddings/methods/create"""

    def __init__(
        self, settings: "Settings", transport: "httpx.AsyncBaseTransport | None" = None
    ) -> None:
        self.settings, self.transport, self.dimension = settings, transport, settings.embedding_dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.settings.embedding_model or not self.settings.llm_api_key.get_secret_value():
            raise ValueError("Embedding model and provider credentials are required")
        async with httpx.AsyncClient(
            transport=self.transport, timeout=self.settings.llm_timeout_s
        ) as client:
            response = await client.post(
                self.settings.llm_base_url.rstrip("/") + "/embeddings",
                headers={"Authorization": "Bearer " + self.settings.llm_api_key.get_secret_value()},
                json={
                    "model": self.settings.embedding_model,
                    "input": texts,
                    "dimensions": self.dimension,
                },
            )
            response.raise_for_status()
            entries = sorted(response.json()["data"], key=lambda entry: entry["index"])
            if [entry["index"] for entry in entries] != list(range(len(texts))):
                raise ValueError("Invalid embedding batch")
            vectors = []
            for entry in entries:
                vector = [float(value) for value in entry["embedding"]]
                if len(vector) != self.dimension or not all(
                    math.isfinite(value) for value in vector
                ):
                    raise ValueError("Embedding dimension or values do not match the schema")
                vectors.append(vector)
            return vectors
