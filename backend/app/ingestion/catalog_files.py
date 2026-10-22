import csv
import io
import posixpath
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from openpyxl import Workbook

from app.core.errors import DomainError

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
HEADERS = [
    "sku",
    "name",
    "aliases",
    "category",
    "description",
    "unit",
    "price",
    "gst_rate",
    "hsn_sac",
    "stock_status",
]


def template_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Catalogue"
    sheet.append(HEADERS)
    sheet.append(
        [
            "CARD-001",
            "Visiting cards",
            "business cards",
            "printing",
            "Single-sided cards",
            "pack",
            "450",
            "18",
            "4911",
            "na",
        ]
    )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def read_table(filename: str, content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if not content or len(content) > 5 * 1024 * 1024:
        raise DomainError("Upload a nonempty catalogue smaller than 5 MB")
    try:
        if filename.lower().endswith(".csv"):
            table = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        elif filename.lower().endswith(".xlsx"):
            table = _xlsx_strings(content)
        else:
            raise DomainError("Catalogue must be CSV or XLSX")
    except (UnicodeError, BadZipFile, ET.ParseError, KeyError) as error:
        raise DomainError("Catalogue file could not be read") from error
    if len(table) < 2 or len(table) > 5001 or len(table[0]) > 100:
        raise DomainError("Catalogue needs headers and 1 to 5000 rows")
    headers = [value.strip() for value in table[0]]
    if any(not h for h in headers) or len(set(headers)) != len(headers):
        raise DomainError("Column headers must be nonempty and unique")
    rows = []
    for row in table[1:]:
        if not any(row):
            continue
        if len(row) > len(headers):
            raise DomainError("Row has more cells than headers")
        rows.append(dict(zip(headers, row + [""] * (len(headers) - len(row)), strict=True)))
    return headers, rows


def _xlsx_strings(content: bytes) -> list[list[str]]:
    # Read raw XML numeric strings: never let a spreadsheet library cast money to float.
    with ZipFile(io.BytesIO(content)) as archive:
        if sum(info.file_size for info in archive.infolist()) > 50 * 1024 * 1024:
            raise DomainError("Expanded workbook exceeds 50 MB")
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = [
                "".join(node.itertext())
                for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find("s:sheets/s:sheet", NS)
        if sheet is None:
            raise DomainError("Workbook has no sheet")
        relation = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        targets = {
            node.attrib["Id"]: node.attrib["Target"]
            for node in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        target = targets[relation]
        sheet_path = (
            target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        )
        result: list[list[str]] = []
        for row in ET.fromstring(archive.read(sheet_path)).findall("s:sheetData/s:row", NS):
            cells: dict[int, str] = {}
            for cell in row.findall("s:c", NS):
                if cell.find("s:f", NS) is not None:
                    raise DomainError("Replace formulas with explicit values before import")
                address = cell.attrib["r"]
                column = 0
                for letter in address:
                    if not letter.isalpha():
                        break
                    column = column * 26 + ord(letter.upper()) - 64
                if column > 100:
                    raise DomainError("Workbook has too many columns")
                kind = cell.attrib.get("t", "n")
                value = cell.findtext("s:v", "", NS)
                if kind == "s":
                    value = shared[int(value)]
                elif kind == "inlineStr":
                    inline = cell.find("s:is", NS)
                    value = "" if inline is None else "".join(inline.itertext())
                cells[column - 1] = value
            if cells:
                result.append([cells.get(i, "") for i in range(max(cells) + 1)])
            if len(result) > 5001:
                raise DomainError("Workbook has too many rows")
        return result
