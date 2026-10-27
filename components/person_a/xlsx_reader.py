"""Small read-only XLSX row reader built from the Python standard library.

It intentionally supports the cell encodings used by the hospital workbooks and
the integration fixtures. Formula evaluation, formatting, and legacy .xls files
are outside this adapter's scope.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
import json
import logging
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"main": MAIN_NS, "rel": REL_NS, "pkg": PACKAGE_REL_NS}


def _column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference.upper())
    if not match:
        raise ValueError(f"Invalid XLSX cell reference: {reference!r}")
    result = 0
    for letter in match.group(1):
        result = result * 26 + ord(letter) - ord("A") + 1
    return result - 1


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{MAIN_NS}}}is")
        return "" if inline is None else "".join(inline.itertext())

    value_node = cell.find(f"{{{MAIN_NS}}}v")
    value = "" if value_node is None or value_node.text is None else value_node.text
    if cell_type == "s" and value:
        return shared_strings[int(value)]
    return value


def _sheet_rows(
    archive: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]
) -> Iterator[tuple[int, list[str]]]:
    root = ET.fromstring(archive.read(sheet_path))
    for row in root.findall("main:sheetData/main:row", NS):
        values: dict[int, str] = {}
        for cell in row.findall("main:c", NS):
            values[_column_index(cell.attrib["r"])] = _cell_value(cell, shared_strings)
        if not values:
            continue
        width = max(values) + 1
        yield int(row.attrib.get("r", "0")), [values.get(index, "") for index in range(width)]


def iter_xlsx_records(
    path: str | Path,
    sheet_predicate: Callable[[str], bool] | None = None,
) -> Iterator[tuple[str, int, dict[str, str]]]:
    """Yield ``(sheet_name, row_number, record)`` using each sheet's first row as headers."""

    workbook_path = Path(path)
    with zipfile.ZipFile(workbook_path) as archive:
        logging.getLogger(__name__).info(json.dumps({
            "event": "xlsx_open", "path": str(workbook_path),
        }, ensure_ascii=True))
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(item.itertext()) for item in shared_root.findall("main:si", NS)
            ]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships.findall("pkg:Relationship", NS)
        }

        for sheet in workbook.findall("main:sheets/main:sheet", NS):
            sheet_name = sheet.attrib["name"]
            if sheet_predicate is not None and not sheet_predicate(sheet_name):
                continue
            relationship_id = sheet.attrib[f"{{{REL_NS}}}id"]
            target = targets[relationship_id]
            sheet_path = target.lstrip("/")
            if not sheet_path.startswith("xl/"):
                sheet_path = posixpath.normpath(posixpath.join("xl", sheet_path))

            rows = _sheet_rows(archive, sheet_path, shared_strings)
            try:
                _, raw_headers = next(rows)
            except StopIteration:
                continue
            headers = [header.strip() for header in raw_headers]
            for row_number, values in rows:
                record = {
                    header: values[index].strip() if index < len(values) else ""
                    for index, header in enumerate(headers)
                    if header
                }
                if any(record.values()):
                    yield sheet_name, row_number, record
