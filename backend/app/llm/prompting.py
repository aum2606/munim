"""Loads Jinja prompt templates from app/agents/prompts. Every template has a `system` block
(trusted instructions) and a `user` block (where untrusted customer text is allowed)."""

import hashlib
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.llm.base import ChatMessage

PROMPT_DIR = Path(__file__).resolve().parent.parent / "agents" / "prompts"
_env = Environment(
    loader=FileSystemLoader(PROMPT_DIR),
    undefined=StrictUndefined,  # a missing variable is a bug, not an empty string
    autoescape=False,  # noqa: S701  (prompts are plain text, not HTML)
    keep_trailing_newline=False,
)
_FENCE_TAG = re.compile(
    r"</?\s*(customer_message|catalogue|knowledge|requirements)[^>]*>", re.IGNORECASE
)


def sanitize_customer_text(text: str) -> str:
    """Stop customer text from closing the delimiter block it is placed in."""
    return _FENCE_TAG.sub("", text)


def prompt_version(name: str) -> str:
    """'<name>@<sha12 of the template and the shared preamble>': changes when either does."""
    source = (PROMPT_DIR / f"{name}.jinja").read_bytes() + (
        PROMPT_DIR / "_preamble.jinja"
    ).read_bytes()
    return f"{name}@{hashlib.sha256(source).hexdigest()[:12]}"


def all_prompt_versions() -> dict[str, str]:
    return {
        p.stem: prompt_version(p.stem)
        for p in sorted(PROMPT_DIR.glob("*.jinja"))
        if not p.stem.startswith("_")
    }


def render_prompt(name: str, **variables: Any) -> tuple[list[ChatMessage], str]:
    """Returns ([system, user] messages, version), so every agent_runs row says exactly which
    prompt produced it."""
    template = _env.get_template(f"{name}.jinja")
    context = template.new_context(variables)
    system = "".join(template.blocks["system"](context)).strip()
    user = "".join(template.blocks["user"](context)).strip()
    version = prompt_version(name)
    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ], version
