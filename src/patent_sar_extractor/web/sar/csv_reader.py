"""A bounded lossless CSV parser and cheap mapping preview; no chemistry inference."""

from __future__ import annotations

import csv
import io
import re

from ..errors import WebError
from .models import CSVPreview

MAX_CSV_BYTES = 8 * 1024 * 1024
MAX_ROWS = 25000
MAX_COLUMNS = 256


def parse_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if not data or len(data) > MAX_CSV_BYTES:
        raise WebError(
            413, "sar_csv_limit", "CSV must contain data and be no larger than 8 MiB."
        )
    try:
        text = data.decode(
            "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        )
        if "\x00" in text:
            raise ValueError("NUL")
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        # Sniffer may mistake literal spreadsheet apostrophes for a quoting
        # convention. Only infer the delimiter; preserve RFC/Excel double quotes
        # and all leading whitespace in the original cells.
        reader = csv.reader(
            io.StringIO(text, newline=""),
            delimiter=dialect.delimiter,
            quotechar='"',
            doublequote=True,
            skipinitialspace=False,
            strict=True,
        )
        headers = next(reader)
        if not 2 <= len(headers) <= MAX_COLUMNS or len(set(headers)) != len(headers):
            raise ValueError("headers")
        if any(not key.strip() or len(key) > 300 for key in headers):
            raise ValueError("headers")
        rows = []
        for raw in reader:
            if not raw:
                continue
            if len(raw) != len(headers) or any(
                len(value) > 128 * 1024 for value in raw
            ):
                raise ValueError("row width")
            rows.append(dict(zip(headers, raw, strict=True)))
            if len(rows) > MAX_ROWS:
                raise WebError(
                    413,
                    "sar_row_limit",
                    "CSV exceeds 25000 rows; no rows were truncated.",
                )
        if not rows:
            raise ValueError("empty")
        return headers, rows
    except (UnicodeError, csv.Error, StopIteration, ValueError) as error:
        raise WebError(
            422,
            "sar_csv_invalid",
            "CSV must have unique headers and complete UTF-8 or UTF-16 records.",
        ) from error


def preview(data: bytes, filename: str, token: str) -> CSVPreview:
    headers, rows = parse_csv(data)
    normalized = {re.sub(r"[\s_-]", "", key.casefold()): key for key in headers}

    def named(*aliases: str) -> str | None:
        return next((normalized[name] for name in aliases if name in normalized), None)

    identity = named(
        "identifierlabel",
        "compoundid",
        "displayid",
        "compound",
        "id",
        "编号",
        "化合物编号",
        "化合物",
    )
    smiles = named("smiles", "canonicalsmiles", "isomericsmiles")
    long = {"metric", "value"}.issubset(headers)
    ignored = {
        identity,
        smiles,
        named("assay"),
        named("target"),
        named("unit"),
        named("cellline"),
        named("duration"),
    }
    candidates = (
        ["value"]
        if long
        else [
            key
            for key in headers
            if key not in ignored
            and any(
                re.fullmatch(
                    r"\s*(?:[<>≤≥~]?\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*(?:[a-zA-Zµμ%/]+)?|[A-G]|\+{1,6})\s*",
                    row[key],
                )
                for row in rows[:20]
            )
        ][:64]
    )
    return CSVPreview(
        token=token,
        filename=filename,
        headers=headers,
        row_count=len(rows),
        samples=rows[:5],
        suggested_id=identity,
        suggested_smiles=smiles,
        suggested_activities=candidates,
    )
