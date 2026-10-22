import re
from dataclasses import dataclass

from app.ingestion.parsers import PageText


@dataclass(frozen=True)
class TextChunk:
    content: str
    page: int
    section: str
    token_count: int


def chunk_pages(pages: list[PageText], size: int = 500, overlap: int = 75) -> list[TextChunk]:
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("Invalid chunk window")
    chunks = []
    section = ""
    for page in pages:
        paragraphs = re.split(r"\n\s*\n", page.content.replace("\r\n", "\n"))
        words: list[str] = []
        for paragraph in paragraphs:
            if paragraph.lstrip().startswith("#"):
                if words:
                    chunks.extend(_windows(words, page.page, section, size, overlap))
                    words = []
                section = paragraph.strip().lstrip("# ")
            else:
                words.extend(paragraph.split())
        if words:
            chunks.extend(_windows(words, page.page, section, size, overlap))
    return chunks


def _windows(words: list[str], page: int, section: str, size: int, overlap: int) -> list[TextChunk]:
    result = []
    start = 0
    while start < len(words):
        window = words[start : start + size]
        result.append(TextChunk(" ".join(window), page, section, len(window)))
        if start + size >= len(words):
            break
        start += size - overlap
    return result
