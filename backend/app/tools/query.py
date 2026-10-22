import re

COMMON = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "do",
    "does",
    "i",
    "you",
    "your",
    "my",
    "me",
    "for",
    "of",
    "to",
    "in",
    "on",
    "please",
    "tell",
    "what",
    "how",
    "much",
    "can",
    "get",
    "have",
    "about",
    "ka",
    "ki",
    "ke",
    "kya",
    "hai",
    "hain",
    "bhai",
    "batao",
    "chahiye",
    "kitna",
    "kitne",
    "aur",
}
COMMERCE = {"price", "pricing", "rate", "cost", "available", "availability", "stock"}
EXPAND = {
    "khula": "open",
    "khuli": "open",
    "timing": "hours",
    "timings": "hours",
    "warranty": "warranty",
    "bhejte": "delivery",
    "deliver": "delivery",
}


def normalize_query(query: str, *, catalog: bool = False) -> str:
    words = [EXPAND.get(word, word) for word in re.findall(r"[\w-]+", query.lower())]
    ignored = COMMON | COMMERCE if catalog else COMMON
    return " ".join(word for word in words if word not in ignored)[:300]
