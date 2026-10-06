"""Bounded local QA inspection of workbook/SDF files and raw JSON."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .activity_identity import normalize_compound


def _load_json(path: Path, default: Any):
    if not path.is_file():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _excel_column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference or "")
    value = 0
    for letter in letters.group(0) if letters else "":
        value = value * 26 + ord(letter) - ord("A") + 1
    return value - 1


def _read_xlsx_values(path: Path) -> dict:
    """Read workbook values without requiring a spreadsheet runtime."""
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    workbook_rel_ns = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    )
    result = {"path": str(path), "sheets": {}, "error": ""}
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in root.findall("a:si", ns):
                    shared_strings.append(
                        "".join(t.text or "" for t in item.findall(".//a:t", ns))
                    )

            rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            relations = {
                rel.get("Id"): rel.get("Target", "")
                for rel in rels_root.findall("r:Relationship", rel_ns)
            }
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            for sheet in workbook.findall("a:sheets/a:sheet", ns):
                name = sheet.get("name", "")
                target = relations.get(sheet.get(f"{{{workbook_rel_ns}}}id"), "")
                if not target:
                    continue
                if target.startswith("/"):
                    sheet_path = target.lstrip("/")
                elif target.startswith("xl/"):
                    sheet_path = target
                else:
                    sheet_path = f"xl/{target}"
                sheet_root = ET.fromstring(archive.read(sheet_path))
                dimension = sheet_root.find("a:dimension", ns)
                rows = []
                for row in sheet_root.findall("a:sheetData/a:row", ns):
                    values = []
                    for cell in row.findall("a:c", ns):
                        index = _excel_column_index(cell.get("r", ""))
                        while len(values) <= index:
                            values.append("")
                        if cell.get("t") == "inlineStr":
                            value = "".join(
                                t.text or "" for t in cell.findall(".//a:t", ns)
                            )
                        else:
                            node = cell.find("a:v", ns)
                            value = (
                                node.text
                                if node is not None and node.text is not None
                                else ""
                            )
                            if cell.get("t") == "s" and value:
                                value = shared_strings[int(value)]
                        values[index] = str(value)
                    rows.append(values)
                result["sheets"][name] = {
                    "dimension": dimension.get("ref", "")
                    if dimension is not None
                    else "",
                    "rows": rows,
                }
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        zipfile.BadZipFile,
        ET.ParseError,
    ) as exc:
        result["error"] = str(exc)
    return result


def _sheet_rows_by_cpd(sheet: dict) -> tuple[list[str], dict[str, dict[str, str]]]:
    rows = sheet.get("rows", []) if isinstance(sheet, dict) else []
    if not rows:
        return [], {}
    headers = [str(value or "").strip() for value in rows[0]]
    order = []
    mapped = {}
    for row in rows[1:]:
        cpd = normalize_compound(row[0] if row else "")
        if not cpd:
            continue
        order.append(cpd)
        mapped[cpd] = {
            header: str(row[index] if index < len(row) else "").strip()
            for index, header in enumerate(headers)
            if header
        }
    return order, mapped


def _worksheet_activity_value(row: dict[str, str], target: str) -> str:
    if target in row:
        return row[target]
    for header, value in row.items():
        if header.startswith((f"{target} ", f"{target} (")):
            return value
    return ""


def _sdf_record_count(path: Path) -> int:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").count("$$$$")
    except OSError:
        return -1


def _select_patent_output_file(files: list[Path], patent_id: str = "") -> Path | None:
    candidates = [p for p in files if p.exists() and p.stat().st_size > 0]
    if not candidates:
        return None
    patent = re.sub(r"[^A-Za-z0-9]+", "", str(patent_id or "")).upper()
    if patent:
        exact = [
            p
            for p in candidates
            if re.sub(r"[^A-Za-z0-9]+", "", p.stem).upper().startswith(patent)
        ]
        if exact:
            return min(exact, key=lambda p: (p.name.lower(), -p.stat().st_mtime))
    return min(candidates, key=lambda p: (-p.stat().st_mtime, p.name.lower()))
