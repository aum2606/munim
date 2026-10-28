import io
from zipfile import BadZipFile, ZipFile

from app.core.errors import DomainError


def validate_document(content: bytes, suffix: str) -> None:
    if suffix == ".txt":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError as error:
            raise DomainError("Text files must use UTF-8") from error
        if "\0" in text:
            raise DomainError("Binary files cannot be uploaded as text")
    elif suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise DomainError("PDF signature does not match its file type")
    elif suffix == ".docx":
        try:
            with ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 2000
                    or sum(entry.file_size for entry in entries) > 50 * 1024 * 1024
                    or "word/document.xml" not in archive.namelist()
                    or any(entry.flag_bits & 1 for entry in entries)
                ):
                    raise DomainError("Upload a bounded, unencrypted DOCX document")
        except BadZipFile as error:
            raise DomainError("DOCX signature does not match its file type") from error
