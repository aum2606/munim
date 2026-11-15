import re

# ~350 words is roughly 500 tokens; overlap is ~15%. Counting words (not tokens) keeps this
# model-independent and works for Devanagari/Gujarati, which whitespace-split reasonably well.
MAX_WORDS = 350
OVERLAP_WORDS = 50


def chunk_text(
    text: str, max_words: int = MAX_WORDS, overlap_words: int = OVERLAP_WORDS
) -> list[str]:
    """Split text into chunks on paragraph boundaries.

    A heading (a paragraph starting with '#') always starts a new chunk. A paragraph longer than
    max_words is cut into overlapping windows. Otherwise paragraphs are packed together, and each
    new chunk starts with the tail of the previous one so context is not lost at the seam.
    """
    chunks: list[str] = []
    current: list[str] = []
    count = 0

    def flush() -> None:
        nonlocal current, count
        if current:
            chunks.append("\n\n".join(current))
        current, count = [], 0

    for paragraph in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not paragraph:
            continue
        words = paragraph.split()
        if len(words) > max_words:
            flush()
            step = max_words - overlap_words
            chunks.extend(" ".join(words[i : i + max_words]) for i in range(0, len(words), step))
            continue
        if current and (count + len(words) > max_words or paragraph.startswith("#")):
            is_heading = paragraph.startswith("#")
            tail = "" if is_heading else " ".join(" ".join(current).split()[-overlap_words:])
            flush()
            if tail:
                current, count = [tail], len(tail.split())
        current.append(paragraph)
        count += len(words)
    flush()
    return chunks
