"""Scripted model replies and sign-in, shared by the integration tests."""

import json
import uuid

import httpx

from tests.conftest import PASSWORD


def router(intent: str = "pricing", confidence: float = 0.9, **extra: object) -> str:
    return json.dumps(
        {"intent": intent, "language": "en", "script": "latin", "confidence": confidence, **extra}
    )


def quote_router(confidence: float = 0.9, **extra: object) -> str:
    return router("quote_request", confidence, **extra)


def knowledge(item_id: uuid.UUID | None = None, **extra: object) -> str:
    body: dict[str, object] = {
        "answer_points": ["Visiting cards are available in matt finish."],
        "cited_item_ids": [str(item_id)] if item_id else [],
        "price_item_ids": [str(item_id)] if item_id else [],
        "grounded": True,
        **extra,
    }
    return json.dumps(body)


def not_grounded() -> str:
    return json.dumps(
        {
            "answer_points": [],
            "cited_item_ids": [],
            "price_item_ids": [],
            "grounded": False,
            "gap_question": "rate?",
        }
    )


def responder(reply: str) -> str:
    return json.dumps({"reply": reply})


async def login(client: httpx.AsyncClient, email: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return str(response.json()["access_token"])
