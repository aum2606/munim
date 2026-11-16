import enum

from app.agents.models import Intent, RouterOutput


class Route(enum.StrEnum):
    KNOWLEDGE = "knowledge"
    QUOTE = "quote"
    HANDOFF = "handoff"
    OFF_TOPIC = "off_topic"
    GREETING = "greeting"


# Order status needs a person: there is no order system to look it up in.
_HANDOFF = {Intent.COMPLAINT, Intent.HUMAN_REQUEST, Intent.NEGOTIATION, Intent.ORDER_FOLLOWUP}
_OFF_TOPIC = {Intent.SPAM, Intent.OFF_TOPIC}


def route_for(
    router: RouterOutput, confidence_threshold: float, quote_flow_active: bool = False
) -> Route:
    """Plain Python decides which agent runs next, never the model (BUILD_PLAN.md section 5.1).

    Complaints, requests for a person, and haggling go to a human; so does anything the router
    is not sure about.
    """
    if router.intent in _HANDOFF:
        return Route.HANDOFF
    if quote_flow_active:  # a short answer like "500" is a reply to our question, not a new topic
        return Route.QUOTE
    if router.confidence < confidence_threshold:
        return Route.HANDOFF
    if router.intent in _OFF_TOPIC:
        return Route.OFF_TOPIC
    if router.intent == Intent.GREETING:  # a fixed welcome, not a lookup that finds nothing
        return Route.GREETING
    if router.intent == Intent.QUOTE_REQUEST:
        return Route.QUOTE
    return Route.KNOWLEDGE
