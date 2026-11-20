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
    r"</?\s*(customer_message|catalogue|knowledge|requirements|evidence)[^>]*>", re.IGNORECASE
)
# Zero-width and bidirectional controls, and C0 controls except newline and tab: they can split a
# delimiter tag so a filter misses it while a model still reads it.
_HIDDEN_RANGES = (  # code points, written as numbers so the source holds no invisible characters
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0xFEFF, 0xFEFF),
    (0x00AD, 0x00AD),
    (0x00, 0x08),
    (0x0B, 0x0C),
    (0x0E, 0x1F),
)
_HIDDEN = re.compile(
    "[" + "".join(re.escape(chr(a)) + "-" + re.escape(chr(z)) for a, z in _HIDDEN_RANGES) + "]"
)


def clean_text(text: str) -> str:
    """Text that will sit inside a prompt, whether a customer wrote it or the shop did: remove
    hidden characters, then anything that could close or open a delimiter block."""
    return _FENCE_TAG.sub("", _HIDDEN.sub("", text))


sanitize_customer_text = clean_text  # the older name, kept for the customer-text call sites

_state = {"canary": "MNM-UNSET"}


def set_canary(value: str) -> None:
    """A secret marker put in every system prompt. A reply that contains it is a prompt leak."""
    _state["canary"] = value
    _env.globals["canary"] = value


def current_canary() -> str:
    return _state["canary"]


_env.globals["canary"] = _state["canary"]


def prompt_version(name: str) -> str:
    """'<name>@<sha12 of the template and the shared preamble>': changes when either does."""
    shared = [PROMPT_DIR / "_preamble.jinja", PROMPT_DIR / "_canary.jinja"]
    source = (PROMPT_DIR / f"{name}.jinja").read_bytes() + b"".join(f.read_bytes() for f in shared)
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
