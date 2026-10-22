import re

from app.llm import Embedder, NoOpReranker, Reranker
from app.repositories.search import SearchRepository
from app.schemas.knowledge import Fact, SearchResults
from app.tools.query import normalize_query

# Knowledge chunks cannot authorize a price. Ignore currency-bearing chunks entirely.
CURRENCY = re.compile(r"\u20b9|\b(?:rs\.?|inr|rupees?|lakh|crore)\b|\d\s*[kK]\b", re.I)


class KnowledgeSearch:
    def __init__(
        self, repository: SearchRepository, embedder: Embedder, reranker: Reranker | None = None
    ) -> None:
        self.repository, self.embedder, self.reranker = (
            repository,
            embedder,
            reranker or NoOpReranker(),
        )

    async def search_knowledge(self, query: str, k: int = 5) -> SearchResults:
        normalized = normalize_query(query)
        vector = (await self.embedder.embed([normalized or query]))[0]
        chunks = await self.repository.knowledge(normalized, vector, min(max(k, 1), 10))
        safe = {str(chunk.id): chunk for chunk in chunks if CURRENCY.search(chunk.content) is None}
        ordered = await self.reranker.rerank(query, list(safe))
        return SearchResults(
            facts=[
                Fact(ref="chunk:" + key, kind="chunk", text=safe[key].content, price=None)
                for key in ordered
                if key in safe
            ]
        )
