from dataclasses import dataclass

from app.core.config import Settings
from app.db.session import SessionMaker
from app.llm.base import LLMClient
from app.llm.embedder import Embedder


@dataclass(frozen=True)
class Deps:
    """Everything the pipeline needs from outside: models, embeddings, settings, database."""

    llm: LLMClient
    embedder: Embedder
    settings: Settings
    sessionmaker: SessionMaker
