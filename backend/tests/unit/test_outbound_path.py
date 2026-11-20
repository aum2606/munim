"""Every message to a customer goes through `send_to_customer`, which queues its delivery."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
ALLOWED = {APP / "services" / "outbound.py"}


def stores_an_outbound_message(call: ast.Call) -> bool:
    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "add_message"):
        return False
    return any(
        k.arg == "direction" and isinstance(k.value, ast.Attribute) and k.value.attr == "OUT"
        for k in call.keywords
    )


def test_no_module_stores_an_outbound_message_without_queueing_its_delivery() -> None:
    offenders = [
        f"{path.relative_to(APP)}:{node.lineno}"
        for path in APP.rglob("*.py")
        if path not in ALLOWED
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and stores_an_outbound_message(node)
    ]
    assert offenders == [], f"use services.outbound.send_to_customer: {offenders}"


def test_the_guard_itself_catches_a_bypass() -> None:
    bypass = ast.parse("await chat.add_message(c, direction=Direction.OUT, content='x')")
    (call,) = [n for n in ast.walk(bypass) if isinstance(n, ast.Call)]
    assert stores_an_outbound_message(call)
