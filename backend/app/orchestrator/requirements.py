"""Checks on what the model says a customer said. The model fills slots; this code decides
which values are acceptable, what is still missing, and when the quote can be prepared."""

from decimal import Decimal, InvalidOperation
from typing import Any

MAX_TEXT = 200
MAX_NUMBER = Decimal(10_000_000)
MAX_QUESTIONS = 2


def slot_definitions(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    properties = schema.get("properties", {})
    return dict(properties) if isinstance(properties, dict) else {}


def required_slots(schema: dict[str, Any]) -> list[str]:
    return [s for s in schema.get("required", []) if s in slot_definitions(schema)]


def _enum_value(options: list[Any], raw: str) -> str | None:
    lowered = raw.strip().lower()
    return next((str(o) for o in options if str(o).lower() == lowered), None)


def _clean_value(definition: dict[str, Any], value: Any) -> Any:
    """The value in its proper type, or None if it is not acceptable for this slot."""
    kind = definition.get("type", "string")
    options = definition.get("enum", [])
    if kind == "array":
        items = value if isinstance(value, list) else [value]
        item_options = definition.get("items", {}).get("enum", [])
        cleaned = [_clean_value({"type": "string", "enum": item_options}, i) for i in items]
        kept = [c for c in cleaned if c is not None]
        return kept or None
    if isinstance(value, bool) or value is None:
        return None
    if kind in ("integer", "number"):
        try:
            number = Decimal(str(value).replace(",", "").strip())
        except InvalidOperation:
            return None
        if not 0 < number <= MAX_NUMBER or (kind == "integer" and number != number.to_integral()):
            return None
        return int(number) if kind == "integer" else str(number.normalize())
    text = str(value).strip()
    if not text:
        return None
    if options:
        return _enum_value(options, text)
    return text[:MAX_TEXT]


def validate_slots(schema: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    """Keep only slots the schema defines, with values of the right type and from the allowed
    options. Anything else the model produced is dropped, never repaired."""
    definitions = slot_definitions(schema)
    clean: dict[str, Any] = {}
    for name, value in proposed.items():
        if name not in definitions:
            continue
        cleaned = _clean_value(definitions[name], value)
        if cleaned is not None:
            clean[name] = cleaned
    return clean


def apply_unknowns(
    schema: dict[str, Any],
    defaults: dict[str, Any],
    filled: dict[str, Any],
    unknown_slots: list[str],
) -> dict[str, Any]:
    """ "Don't know": use the schema's default for that slot, or mark it as not specified so the
    team sees it and the quote is not held up."""
    definitions = slot_definitions(schema)
    result = dict(filled)
    for name in unknown_slots:
        if name in definitions and name not in result:
            result[name] = defaults.get(name, "not specified")
    return result


def missing_slots(schema: dict[str, Any], filled: dict[str, Any]) -> list[str]:
    return [s for s in required_slots(schema) if s not in filled]


def next_questions(proposed: list[str], missing: list[str], hints: dict[str, str]) -> list[str]:
    """At most two questions. The model's own wording if it gave any, else our hints."""
    questions = [q.strip()[:300] for q in proposed if q.strip()][:MAX_QUESTIONS]
    if questions:
        return questions
    return [
        hints.get(slot, f"Could you tell us the {slot.replace('_', ' ')}?") for slot in missing
    ][:MAX_QUESTIONS]
