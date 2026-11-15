import io

import docx
from pypdf import PdfReader

from app.db.models import DocumentSource

MAX_PAGES = 300  # bounds work on a hostile or huge PDF


def extract_text(content: bytes, source: DocumentSource) -> str:
    """Plain text from an upload. Headings in Word files become '# ' lines so the chunker can
    start a new chunk at each. Raises ValueError if there is nothing to index."""
    if source == DocumentSource.PDF:
        reader = PdfReader(io.BytesIO(content), strict=False)
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages[:MAX_PAGES])
    elif source == DocumentSource.DOCX:
        text = _docx_text(content)
    else:
        text = content.decode("utf-8-sig", errors="replace")
    if not text.strip():
        raise ValueError("no text found in the file (a scanned PDF needs OCR)")
    return text


def _docx_text(content: bytes) -> str:
    document = docx.Document(io.BytesIO(content))
    parts: list[str] = []
    for paragraph in document.paragraphs:
        if not paragraph.text.strip():
            continue
        style = paragraph.style
        is_heading = style is not None and (style.name or "").startswith("Heading")
        parts.append(f"# {paragraph.text}" if is_heading else paragraph.text)
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n\n".join(parts)
