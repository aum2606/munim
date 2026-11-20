"""Detecting a reply that repeats the system prompt. Pure Python, no LLM.

Two independent signals, so beating one is not enough:
- the **canary**: a secret marker, different for every deployment, written into every system prompt.
  A reply that contains it, however spaced or cased, has copied the prompt.
- **overlap**: a reply that shares a run of 6 consecutive words with the instructions has copied
  them, even without the canary (the model was asked to paraphrase or quote part of them).

Known limit: a *translation* of the instructions shares neither. That needs the model's own refusal
(the preamble tells it to) and the owner approving quotations; it is listed in DECISIONS.md.
"""

import re
from functools import cache
from pathlib import Path

from app.agents.amounts import normalise
from app.llm import prompting

SHINGLE = 6
_WORD = re.compile(r"\w+", re.UNICODE)
_JINJA = re.compile(r"\{[{%#].*?[}%#]\}", re.DOTALL)
_SYSTEM_BLOCK = re.compile(r"\{%\s*block system\s*%\}(.*?)\{%\s*endblock\s*%\}", re.DOTALL)


def _words(text: str) -> list[str]:
    return _WORD.findall(normalise(text).lower())


def _shingles(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


@cache
def _prompt_shingles(prompt_dir: str) -> frozenset[tuple[str, ...]]:
    """Every 7-word run in the static text of every system prompt (template tags removed)."""
    found: set[tuple[str, ...]] = set()
    for path in sorted(Path(prompt_dir).glob("*.jinja")):
        source = path.read_text(encoding="utf-8")
        for block in _SYSTEM_BLOCK.findall(source) or [source]:
            for chunk in _JINJA.split(block):  # a tag splits the text: runs never span it
                found |= _shingles(_words(chunk))
    return frozenset(found)


def leaks_canary(reply: str) -> bool:
    canary = prompting.current_canary().lower()
    squashed = re.sub(r"[\s\W_]+", "", normalise(reply).lower())  # "m n m - 1 2" still matches
    return re.sub(r"[\s\W_]+", "", canary) in squashed


def overlaps_prompt(reply: str) -> bool:
    return not _prompt_shingles(str(prompting.PROMPT_DIR)).isdisjoint(_shingles(_words(reply)))
