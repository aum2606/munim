import enum

from app.agents.models import Intent, RouterOutput


class Route(enum.StrEnum):
    KNOWLEDGE = "knowledge"
    QUOTE = "quote"
    HANDOFF = "handoff"
    OFF_TOPIC = "off_topic"


_HANDOFF = {Intent.COMPLAINT, Intent.HUMAN_REQUEST, Intent.NEGOTIATION}
_OFF_TOPIC = {Intent.SPAM, Intent.OFF_TOPIC}


def route_for(router: RouterOutput, confidence_threshold: float) -> Route:
    """Plain Python decides which agent runs next, never the model (BUILD_PLAN.md section 5.1).

    Complaints, requests for a person, and haggling go to a human; so does anything the router
    is not sure about.
    """
    if router.confidence < confidence_threshold or router.intent in _HANDOFF:
        return Route.HANDOFF
    if router.intent in _OFF_TOPIC:
        return Route.OFF_TOPIC
    if router.intent == Intent.QUOTE_REQUEST:
        return Route.QUOTE
    return Route.KNOWLEDGE
