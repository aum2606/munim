from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from app.agents.models import Intent, Language, Script

ITEMS_DIR = Path(__file__).parent / "items"


class Expect(BaseModel):
    grounded: bool  # should the bot be able to answer from the shop's own data?
    skus: list[str] = Field(default_factory=list)  # catalogue items a correct answer is based on
    faq: str | None = None  # title of the FAQ a correct answer is based on
    price_paise: list[int] = Field(default_factory=list)  # the only amounts a reply may contain


class BenchItem(BaseModel):
    id: str
    vertical: Literal["printing", "photography"]
    language: Language
    script: Script
    text: str  # what the customer typed
    intent: Intent
    terms: list[str] = Field(default_factory=list)  # product names the router should extract
    expect: Expect
    handoff: bool = False  # should a human take over?
    semantic: bool = False  # needs multilingual embeddings to find the answer
    note: str | None = None


def load_items(directory: Path = ITEMS_DIR) -> list[BenchItem]:
    items = [
        BenchItem.model_validate(row)
        for path in sorted(directory.glob("*.yaml"))
        for row in yaml.safe_load(path.read_text(encoding="utf-8"))
    ]
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark item ids must be unique")
    return items
