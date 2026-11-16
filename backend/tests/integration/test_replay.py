"""The replay gate: a prompt edit that breaks price handling fails it; a harmless one passes."""

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from jinja2 import FileSystemLoader

from app.core.config import Settings
from app.db.session import SessionMaker
from app.llm import prompting
from app.llm.embedder import FakeEmbedder
from benchmark.oracle import OracleLLM
from benchmark.replay import BASELINES, Diff, compare, snapshot
from benchmark.run import evaluate
from benchmark.schema import load_items


async def replay(sessionmaker: SessionMaker, settings: Settings) -> Diff:
    outcomes = await evaluate(
        sessionmaker, settings, FakeEmbedder(), OracleLLM(), load_items(), include_semantic=False
    )
    baseline = json.loads((BASELINES / "oracle.json").read_text(encoding="utf-8"))
    return compare(baseline, snapshot("oracle", outcomes, oracle=True))


def edit_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, edit: Any) -> None:
    """Point the prompt loader at a copy of the templates with one of them edited."""
    copy = tmp_path / "prompts"
    shutil.copytree(prompting.PROMPT_DIR, copy)
    path = copy / f"{name}.jinja"
    text = path.read_text(encoding="utf-8")
    edited = edit(text)
    assert edited != text, "the edit did not change the template"
    path.write_text(edited, encoding="utf-8")
    monkeypatch.setattr(prompting, "PROMPT_DIR", copy)
    monkeypatch.setattr(prompting._env, "loader", FileSystemLoader(copy))  # noqa: SLF001
    prompting._env.cache.clear()  # noqa: SLF001


@pytest.fixture(autouse=True)
def fresh_template_cache() -> Any:
    prompting._env.cache.clear()  # noqa: SLF001
    yield
    prompting._env.cache.clear()  # noqa: SLF001


async def test_the_current_prompts_pass_the_committed_baseline(
    sessionmaker: SessionMaker, settings: Settings
) -> None:
    diff = await replay(sessionmaker, settings)
    assert diff.ok, diff.markdown()
    assert diff.prompts_changed == [], "prompts changed: re-save the baseline (make replay-save)"
    assert diff.price_before == diff.price_after == 100.0


async def test_a_prompt_that_stops_passing_the_price_lines_is_caught(
    sessionmaker: SessionMaker, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The broken responder prompt no longer hands the model the price lines.
    edit_prompt(
        monkeypatch,
        tmp_path,
        "responder",
        lambda t: re.sub(r"Price lines \(copy exactly\):.*?\{% endfor %\}", "", t, flags=re.DOTALL),
    )
    diff = await replay(sessionmaker, settings)
    assert not diff.ok
    assert diff.price_dropped and (diff.price_after or 100) < 100
    assert any(r.endswith("price_ok") for r in diff.regressions)
    assert any(p.startswith("responder:") for p in diff.prompts_changed)
    assert "FAIL" in diff.markdown()


async def test_a_harmless_wording_edit_is_reported_but_passes(
    sessionmaker: SessionMaker, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    edit_prompt(
        monkeypatch,
        tmp_path,
        "responder",
        lambda t: t.replace("chat-friendly", "friendly, chat-style"),
    )
    diff = await replay(sessionmaker, settings)
    assert diff.ok
    assert [p.split(":")[0] for p in diff.prompts_changed] == ["responder"]


# --- the comparison itself ---------------------------------------------------------------------


def run(**items: dict[str, Any]) -> dict[str, Any]:
    full = {
        "intent_ok": True,
        "handoff_ok": True,
        "grounded_ok": True,
        "retrieval_ok": None,
        "price_ok": True,
        "amounts": [25000],
        "hallucinated": 0,
    }
    return {
        "prompts": {"responder": "responder@aaa"},
        "summary": {"price_accuracy": 100.0},
        "items": {name: {**full, **change} for name, change in items.items()},
    }


def test_identical_runs_pass() -> None:
    assert compare(run(a={}, b={}), run(a={}, b={})).ok


def test_something_right_that_becomes_wrong_is_a_regression() -> None:
    diff = compare(run(a={}), run(a={"grounded_ok": False}))
    assert diff.regressions == ["a: grounded_ok"] and not diff.ok


def test_getting_better_is_reported_and_passes() -> None:
    diff = compare(run(a={"grounded_ok": False}), run(a={}))
    assert diff.improvements == ["a: grounded_ok"] and diff.ok


def test_a_not_applicable_check_is_never_a_regression() -> None:
    assert compare(run(a={}), run(a={"retrieval_ok": None, "price_ok": None})).ok


def test_an_amount_that_is_not_allowed_fails_even_if_nothing_else_changed() -> None:
    assert not compare(run(a={}), run(a={"hallucinated": 1})).ok


def test_a_lower_price_accuracy_fails() -> None:
    current = run(a={})
    current["summary"]["price_accuracy"] = 98.0
    assert compare(run(a={}), current).price_dropped


def test_an_item_that_silently_stops_running_fails() -> None:
    diff = compare(run(a={}, b={}), run(a={}))
    assert diff.missing == ["b"] and not diff.ok


def test_new_items_and_changed_amounts_are_reported() -> None:
    diff = compare(run(a={}), run(a={"amounts": [30000]}, c={}))
    assert diff.new == ["c"] and diff.amount_changes == ["a: [25000] -> [30000]"]
    assert diff.ok  # a changed amount alone is information; price_ok decides if it is wrong


def test_changed_prompts_are_listed() -> None:
    current = run(a={})
    current["prompts"] = {"responder": "responder@bbb", "router": "router@ccc"}
    diff = compare(run(a={}), current)
    assert diff.prompts_changed == [
        "responder: responder@aaa -> responder@bbb",
        "router: new -> router@ccc",
    ]
