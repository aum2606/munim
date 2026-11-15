"""Validation and storage of uploaded files. Uploads are untrusted: check what the bytes are, not
what the filename or Content-Type claims, and never let the client choose where a file is stored.
"""

import io
import uuid
import zipfile
from pathlib import Path

from fastapi import UploadFile

from app.core.errors import FileRejectedError
from app.db.models import DocumentSource

_OFFICE_MARKER = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml"}


def _is_office_zip(content: bytes, kind: str) -> bool:
    if not content.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return _OFFICE_MARKER[kind] in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _is_text(content: bytes) -> bool:
    if b"\x00" in content:
        return False
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return True


def sniff_document(content: bytes) -> DocumentSource:
    if content.startswith(b"%PDF-"):
        return DocumentSource.PDF
    if _is_office_zip(content, "docx"):
        return DocumentSource.DOCX
    if _is_text(content):
        return DocumentSource.TXT
    raise FileRejectedError("Upload a PDF, Word (.docx) or plain text file")


def sniff_spreadsheet(content: bytes) -> str:
    """Returns 'xlsx' or 'csv'."""
    if _is_office_zip(content, "xlsx"):
        return "xlsx"
    if _is_text(content):
        return "csv"
    raise FileRejectedError("Upload an Excel (.xlsx) or CSV file")


def save_upload(storage_dir: str, tenant_id: uuid.UUID, content: bytes, extension: str) -> str:
    """Write under <storage_dir>/<tenant_id>/<random>.<ext>. Returns the path relative to
    storage_dir, which is what gets stored in the database."""
    relative = Path(str(tenant_id)) / f"{uuid.uuid4().hex}.{extension}"
    target = Path(storage_dir) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return relative.as_posix()


def read_upload(storage_dir: str, relative: str) -> bytes:
    root = Path(storage_dir).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):  # a stored path must never escape the storage dir
        raise FileRejectedError("Invalid file path")
    return path.read_bytes()


async def read_limited(file: UploadFile, max_mb: int) -> bytes:
    """Read an upload, refusing anything over the size limit without loading all of it."""
    limit = max_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise FileRejectedError(f"The file is larger than {max_mb} MB")
    if not content:
        raise FileRejectedError("The file is empty")
    return content
