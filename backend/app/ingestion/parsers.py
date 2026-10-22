import io
from dataclasses import dataclass
from zipfile import ZipFile

from docx import Document as WordDocument
from pypdf import PdfReader

from app.core.errors import DomainError
from app.db.models.knowledge import SourceType


@dataclass(frozen=True)
class PageText:
    content: str
    page: int


def parse_document(content: bytes, source: SourceType) -> list[PageText]:
    if source in {SourceType.TXT, SourceType.FAQ}:
        try:
            return [PageText(content.decode("utf-8-sig"), 1)]
        except UnicodeError as error:
            raise DomainError("Text files must use UTF-8") from error
    if source == SourceType.PDF:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise DomainError("Upload an unencrypted PDF")
        return [
            PageText(page.extract_text() or "", index) for index, page in enumerate(reader.pages, 1)
        ]
    with ZipFile(io.BytesIO(content)) as archive:
        if sum(member.file_size for member in archive.infolist()) > 50 * 1024 * 1024:
            raise DomainError("Expanded document exceeds 50 MB")
    document = WordDocument(io.BytesIO(content))
    paragraphs = [
        ("# " if paragraph.style is not None and paragraph.style.name.startswith("Heading") else "")
        + paragraph.text
        for paragraph in document.paragraphs
    ]
    return [PageText("\n\n".join(paragraphs), 1)]
