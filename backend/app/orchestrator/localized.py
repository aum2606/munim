FALLBACKS = {
    "en": "Let me confirm this with the team and get back to you.",
    "hinglish": "Main team se confirm karke aapko bataunga.",
    "gujlish": "Hu team sathe tapas karine tamne janavish.",
    "hi": "मैं टीम से पुष्टि करके बताता हूँ।",
    "gu": "હું ટીમ સાથે તપાસ કરીને જણાવીશ.",
}


def fallback(language: str) -> str:
    return FALLBACKS.get(language, FALLBACKS["en"])


def greeting(language: str) -> str:
    return (
        "Namaste! Main aapki kya madad kar sakta hoon?"
        if language == "hinglish"
        else "Hello! How can I help you?"
    )


def grounded_message(language: str, facts: list[str]) -> str:
    prefix = "Yeh details hain: " if language == "hinglish" else ""
    selected: list[str] = []
    for fact in facts:
        if len(prefix + "\n".join(selected + [fact])) > 3900:
            break
        selected.append(fact)
    return prefix + "\n".join(selected)
