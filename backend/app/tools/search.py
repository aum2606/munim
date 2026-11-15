"""Hybrid retrieval: vector similarity + Postgres full-text, merged with Reciprocal Rank Fusion."""

import re
from collections.abc import Callable, Hashable

from app.llm.embedder import Embedder
from app.repositories.documents import ChunkHit, DocumentRepository

# Words that match nearly everything and so rank noise. Kept tiny and multilingual on purpose;
# the vector side of the search handles meaning.
_STOPWORD_TEXT = (
    "a an the is are of to for in on at and or my me you your it this that what which how much "
    "ka ki ke ko hai hain kya kitna kitne kitni bhai mujhe mera aap hum se mein par "
    "che chhe mane mate shu su ketla ketlu tame ame "
    "की का के को है हैं क्या कितना कितने मुझे "
    "નો ની નું ના છે શું કેટલું કેટલા"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())
# Letters in any script, plus Devanagari and Gujarati combining marks that \w would split on.
_TOKEN = re.compile(r"[\wऀ-ॿ઀-૿]+")


def build_tsquery(text: str) -> str | None:
    """An OR query of the meaningful words. Each word is quoted, so customer text can never
    inject tsquery operators. Returns None if nothing useful is left."""
    words = dict.fromkeys(
        w for w in _TOKEN.findall(text.lower()) if len(w) > 1 and w not in _STOPWORDS
    )
    return " | ".join(f"'{w}'" for w in words) or None


def rrf[T](rank_lists: list[list[T]], key: Callable[[T], Hashable], k: int = 60) -> list[T]:
    """Reciprocal Rank Fusion: an item scores 1/(k+rank) in each list it appears in."""
    scores: dict[Hashable, float] = {}
    first_seen: dict[Hashable, T] = {}
    for ranked in rank_lists:
        for rank, item in enumerate(ranked, start=1):
            scores[key(item)] = scores.get(key(item), 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(key(item), item)
    return [first_seen[ident] for ident in sorted(scores, key=lambda i: scores[i], reverse=True)]


async def search_knowledge(
    repo: DocumentRepository, embedder: Embedder, query: str, max_distance: float, limit: int = 5
) -> list[ChunkHit]:
    (vector,) = await embedder.embed([query])
    by_vector = await repo.by_vector(vector, limit * 2, max_distance)
    tsquery = build_tsquery(query)
    by_text = await repo.by_text(tsquery, limit * 2) if tsquery else []
    return rrf([by_vector, by_text], key=lambda hit: hit.chunk_id)[:limit]
