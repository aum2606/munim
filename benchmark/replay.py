"""Replay regression: `make replay`.

Runs the benchmark with the prompts and code in this working tree (TO) and compares it with a saved
baseline (FROM): per item, did anything that was right become wrong, did an amount change, did a
prompt change. The gate fails on any regression, any amount that is not allowed, or a lower price
accuracy, so a prompt edit that breaks price handling cannot be merged.

    python -m benchmark.replay                      # compare with baselines/oracle.json
    python -m benchmark.replay --save               # accept this run as the new baseline
    EVAL_USE_REAL_LLM=1 python -m benchmark.replay --llm real --embedder local --from mymodel

CI uses the oracle model, which answers faithfully from whatever the prompts feed it. It therefore
catches a prompt or pipeline edit that drops data the answer needs, not a change in wording a real
model might misread; for that, save a baseline from a real model and replay against it.
"""

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.guardrails import extract_amounts
from app.llm.prompting import all_prompt_versions
from benchmark.run import REPORTS, Outcome, evaluate, runtime, summarize
from benchmark.schema import load_items

BASELINES = Path(__file__).parent / "baselines"
CHECKS = ("intent_ok", "handoff_ok", "grounded_ok", "retrieval_ok", "price_ok")


def snapshot(
    name: str, outcomes: list[Outcome], *, oracle: bool, prompts: dict[str, str] | None = None
) -> dict[str, Any]:
    """What a baseline stores: enough to diff, nothing customer-specific."""
    return {
        "name": name,
        "prompts": prompts if prompts is not None else all_prompt_versions(),
        "summary": summarize(outcomes, oracle=oracle),
        "items": {
            o.item.id: {
                **{check: getattr(o, check) for check in CHECKS},
                "amounts": sorted(extract_amounts(o.reply)),
                "hallucinated": len(o.hallucinated),
            }
            for o in outcomes
        },
    }


@dataclass
class Diff:
    regressions: list[str] = field(default_factory=list)  # "item: check" was right, now wrong
    improvements: list[str] = field(default_factory=list)
    amount_changes: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # in the baseline, not run now
    new: list[str] = field(default_factory=list)
    prompts_changed: list[str] = field(default_factory=list)
    hallucinated: int = 0
    price_before: float | None = None
    price_after: float | None = None

    @property
    def price_dropped(self) -> bool:
        return (
            self.price_before is not None
            and self.price_after is not None
            and self.price_after < self.price_before
        )

    @property
    def ok(self) -> bool:
        return not (self.regressions or self.missing or self.hallucinated or self.price_dropped)

    def markdown(self) -> str:
        lines = [
            "# Replay",
            "",
            f"Gate: **{'pass' if self.ok else 'FAIL'}**",
            "",
            "| | |",
            "|---|---|",
            f"| price accuracy | {self.price_before} -> {self.price_after} |",
            f"| amounts that are not allowed | {self.hallucinated} |",
            f"| regressions | {len(self.regressions)} |",
            f"| improvements | {len(self.improvements)} |",
            f"| prompts changed | {len(self.prompts_changed)} |",
        ]
        for title, items in (
            ("Regressions (right before, wrong now)", self.regressions),
            ("Baseline items that were not run", self.missing),
            ("Prompts changed", self.prompts_changed),
            ("Amounts that changed", self.amount_changes),
            ("Improvements", self.improvements),
            ("New items (not in the baseline)", self.new),
        ):
            if items:
                lines += ["", f"## {title}", ""] + [f"- {i}" for i in items]
        return "\n".join(lines) + "\n"


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> Diff:
    diff = Diff(
        hallucinated=sum(i["hallucinated"] for i in current["items"].values()),
        price_before=baseline["summary"]["price_accuracy"],
        price_after=current["summary"]["price_accuracy"],
    )
    for agent, version in current["prompts"].items():
        before = baseline["prompts"].get(agent)
        if before != version:
            diff.prompts_changed.append(f"{agent}: {before or 'new'} -> {version}")
    for item_id, before in baseline["items"].items():
        now = current["items"].get(item_id)
        if now is None:
            diff.missing.append(item_id)
            continue
        for check in CHECKS:
            if before[check] is True and now[check] is False:
                diff.regressions.append(f"{item_id}: {check}")
            elif before[check] is False and now[check] is True:
                diff.improvements.append(f"{item_id}: {check}")
        if before["amounts"] != now["amounts"]:
            diff.amount_changes.append(f"{item_id}: {before['amounts']} -> {now['amounts']}")
    diff.new = sorted(set(current["items"]) - set(baseline["items"]))
    return diff


async def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the benchmark against a baseline")
    parser.add_argument("--llm", choices=["fake", "real"], default="fake")
    parser.add_argument("--embedder", choices=["fake", "local"], default="fake")
    parser.add_argument("--from", dest="baseline", default="oracle", help="baseline name")
    parser.add_argument("--save", action="store_true", help="write this run as the baseline")
    args = parser.parse_args()

    async with runtime(args.llm, args.embedder) as (sessionmaker, settings, embedder, llm):
        outcomes = await evaluate(
            sessionmaker,
            settings,
            embedder,
            llm,
            load_items(),
            include_semantic=args.embedder == "local",
        )
    current = snapshot(args.baseline, outcomes, oracle=args.llm == "fake")
    path = BASELINES / f"{args.baseline}.json"
    if args.save:
        BASELINES.mkdir(exist_ok=True)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Saved baseline {path.name}: {len(current['items'])} items")
        return 0
    diff = compare(json.loads(path.read_text(encoding="utf-8")), current)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "replay.md").write_text(diff.markdown(), encoding="utf-8")
    print(diff.markdown())
    return 0 if diff.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
