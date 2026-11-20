import io
import os
import zipfile
from pathlib import Path

import docx
import pytest
from pypdf import PdfWriter

from app.core.errors import FileRejectedError
from app.db.models import DocumentSource
from app.ingestion.chunker import chunk_text
from app.ingestion.parsers import extract_text
from app.ingestion.uploads import read_upload, save_upload, sniff_document, sniff_spreadsheet


def _words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_short_text_is_one_chunk() -> None:
    assert chunk_text("Hello there.\n\nSecond paragraph.") == ["Hello there.\n\nSecond paragraph."]


def test_empty_text_has_no_chunks() -> None:
    assert chunk_text("  \n\n \n") == []


def test_paragraphs_pack_up_to_the_limit_and_overlap() -> None:
    text = "\n\n".join([_words(200, "a"), _words(200, "b"), _words(200, "c")])
    chunks = chunk_text(text, max_words=300, overlap_words=20)
    assert len(chunks) == 3
    # each later chunk opens with the tail of the one before it
    assert chunks[1].startswith("a180 ") and "a199" in chunks[1].split("\n\n")[0]
    assert all(len(c.split()) <= 300 + 20 for c in chunks)


def test_a_huge_paragraph_is_cut_into_overlapping_windows() -> None:
    chunks = chunk_text(_words(1000), max_words=400, overlap_words=50)
    assert len(chunks) >= 3
    first_tail = chunks[0].split()[-50:]
    assert chunks[1].split()[:50] == first_tail
    covered = {w for c in chunks for w in c.split()}
    assert covered == set(_words(1000).split())  # nothing is dropped


def test_headings_start_a_new_chunk_without_carrying_overlap() -> None:
    chunks = chunk_text("# Returns\n\nWithin 7 days.\n\n# Delivery\n\nFree above 500.")
    assert chunks == ["# Returns\n\nWithin 7 days.", "# Delivery\n\nFree above 500."]


def test_hindi_text_is_chunked_like_any_other() -> None:
    assert chunk_text("हमारी दुकान सुबह दस बजे खुलती है।") == ["हमारी दुकान सुबह दस बजे खुलती है।"]


def _docx_bytes() -> bytes:
    document = docx.Document()
    document.add_heading("Refund policy", level=1)
    document.add_paragraph("Refunds within 7 days.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Item"
    table.rows[0].cells[1].text = "Rate"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_docx_text_marks_headings_and_includes_tables() -> None:
    text = extract_text(_docx_bytes(), DocumentSource.DOCX)
    assert "# Refund policy" in text and "Refunds within 7 days." in text and "Item | Rate" in text


def test_txt_text_and_empty_files() -> None:
    assert extract_text("नमस्ते".encode(), DocumentSource.TXT) == "नमस्ते"
    with pytest.raises(ValueError):
        extract_text(b"   \n ", DocumentSource.TXT)


def test_pdf_without_text_is_reported() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError, match="no text"):
        extract_text(buffer.getvalue(), DocumentSource.PDF)


def test_sniffing_goes_by_content_not_name() -> None:
    assert sniff_document(b"%PDF-1.7 ...") == DocumentSource.PDF
    assert sniff_document(_docx_bytes()) == DocumentSource.DOCX
    assert sniff_document(b"plain text") == DocumentSource.TXT
    with pytest.raises(FileRejectedError):
        sniff_document(b"\x00\x01\x02binary")
    with pytest.raises(FileRejectedError):
        sniff_document(b"\xff\xfe invalid utf8 \xff")


def test_a_zip_that_is_not_office_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("evil.exe", "x")
    with pytest.raises(FileRejectedError):
        sniff_spreadsheet(buffer.getvalue())
    with pytest.raises(FileRejectedError):
        sniff_document(buffer.getvalue())  # a zip without word/document.xml is not a .docx


def test_spreadsheet_sniffing() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    assert sniff_spreadsheet(buffer.getvalue()) == "xlsx"
    assert sniff_spreadsheet(b"sku,name,price\nA,B,1") == "csv"
    with pytest.raises(FileRejectedError):
        sniff_spreadsheet(b"\x00\x00binary")


def test_storage_uses_random_names_and_blocks_traversal(tmp_path: Path) -> None:
    import uuid

    tenant = uuid.uuid4()
    relative = save_upload(str(tmp_path), tenant, b"data", "xlsx")
    assert relative.startswith(f"{tenant}/") and relative.endswith(".xlsx")
    assert read_upload(str(tmp_path), relative) == b"data"
    with pytest.raises(FileRejectedError):
        read_upload(str(tmp_path), "../../etc/passwd")


# --- zip bombs --------------------------------------------------------------------------------


def _zip_with(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_an_office_file_that_unpacks_to_far_more_than_it_weighs_is_refused() -> None:
    bomb = _zip_with({"word/document.xml": b"0" * (8 * 1024 * 1024)})  # 8 MB of zeros: a few KB
    assert len(bomb) < 20_000
    with pytest.raises(FileRejectedError, match="once unpacked"):
        sniff_document(bomb)
    sheet = _zip_with({"xl/workbook.xml": b"0" * (8 * 1024 * 1024)})
    with pytest.raises(FileRejectedError, match="once unpacked"):
        sniff_spreadsheet(sheet)


def test_a_total_unpacked_size_or_entry_count_over_the_limit_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ingestion import uploads  # noqa: PLC0415

    monkeypatch.setattr(uploads, "MAX_UNPACKED_BYTES", 1000)
    with pytest.raises(FileRejectedError):
        sniff_document(_zip_with({"word/document.xml": b"<w/>", "word/big.bin": os.urandom(2000)}))
    monkeypatch.setattr(uploads, "MAX_UNPACKED_BYTES", 10**9)
    monkeypatch.setattr(uploads, "MAX_ZIP_ENTRIES", 3)
    many = {"word/document.xml": b"<w/>", **{f"word/p{i}.xml": b"x" for i in range(5)}}
    with pytest.raises(FileRejectedError):
        sniff_document(_zip_with(many))


def test_ordinary_office_files_still_pass_the_bomb_check() -> None:
    assert sniff_document(_docx_bytes()) == DocumentSource.DOCX
    big_but_real = _zip_with({"word/document.xml": os.urandom(900_000)})  # incompressible, 0.9 MB
    assert sniff_document(big_but_real) == DocumentSource.DOCX
