"""Cell-owned biology table extraction, independent of PDF/OCR reading order.

The existing ruled-grid detector is supplied by the activity adapter. This
module owns only biology schemas and their cell evidence, not a second pipeline.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

import cv2

from .table_cells import cell_image, read_cell

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BiologySchema:
    table_id: str
    keys: tuple[str, ...]
    kinds: tuple[str, ...]
    pairs: int = 1
    target: str | None = None
    assay: str | None = None
    cell_line: str | None = None


@dataclass
class BiologyRecord:
    compound: str
    values: dict[str, str]
    page_no: int
    table_id: str
    evidence: dict
    needs_review: bool = False
    notes: str = ""


def infer_schema(context: str, columns: int) -> BiologySchema | None:
    """Require observed biology/header semantics, never specific table numbers."""
    matches = list(re.finditer(r"\bTable\s+(\d+)\b", context, re.I))
    if not matches or not re.search(
        r"Example\s*(?:ID|#)|Compound\s*(?:ID|No)", context, re.I
    ):
        return None
    table_id = f"Table {matches[-1].group(1)}"
    if (
        columns == 3
        and re.search(r"\bHTRF\b", context, re.I)
        and re.search(r"\bRatio\b", context, re.I)
    ):
        target = re.search(
            r"([A-Za-z][A-Za-z0-9-]*)\s+binding\s+measured", context, re.I
        )
        prefix = f"{target.group(1)} HTRF" if target else "HTRF"
        return BiologySchema(
            table_id,
            (f"{prefix} ratio", f"{prefix} grade"),
            ("number", "plus"),
            target=target.group(1) if target else None,
            assay="HTRF",
        )
    if columns in {2, 4} and re.search(r"degradation", context, re.I):
        cell_lines = re.findall(r"\b([A-Za-z][A-Za-z0-9-]{1,14})\s+cells\b", context)
        protein = re.search(r"Ranking\s+of\s+([A-Za-z][A-Za-z0-9-]*)", context, re.I)
        if protein is None:
            proteins = list(
                re.finditer(r"([A-Za-z][A-Za-z0-9-]*)\s+degradation", context, re.I)
            )
            protein = proteins[-1] if proteins else None
        target = (
            protein.group(1)
            if protein and protein.group(1).lower() != "protein"
            else "Protein"
        )
        prefix = f"{cell_lines[-1]} " if cell_lines else ""
        return BiologySchema(
            table_id,
            (f"{prefix}{target} degradation grade",),
            ("letter",),
            columns // 2,
            target=target if target != "Protein" else None,
            assay="Western blot"
            if re.search(r"Western\s+blot", context, re.I)
            else None,
            cell_line=cell_lines[-1] if cell_lines else None,
        )
    if columns == 2 and re.search(r"anti[-\s]?proliferation", context, re.I):
        return BiologySchema(
            table_id,
            ("Anti-proliferation activity grade",),
            ("plus",),
            assay="Anti-proliferation",
        )
    return None


def extract_tables(
    doc,
    pages: list[int],
    *,
    tokens_for_page: Callable,
    grids_for_page: Callable,
) -> list[BiologyRecord]:
    records: list[BiologyRecord] = []
    carry: tuple[BiologySchema, list[float], int] | None = None
    for page_idx in sorted(set(pages)):
        if not 0 <= page_idx < len(doc):
            continue
        page = doc[page_idx]
        grids = sorted(grids_for_page(page), key=lambda grid: grid["bbox"][1])
        if not grids:
            continue
        tokens = tokens_for_page(page)
        native = bool(page.get_text("words"))
        for grid in grids:
            xs, ys = grid["xs"], grid["ys"]
            y0 = ys[0]
            prefix = " ".join(
                t["text"]
                for t in sorted(tokens, key=lambda t: (round(t["y"] / 3), t["x"]))
                if max(0, y0 - 310) <= t["y"] <= ys[1]
            )
            schema = infer_schema(prefix, len(xs) - 1)
            first_row = 1 if schema else 0
            if schema is None and y0 < 130 and carry:
                old, old_xs, old_page = carry
                if (
                    page_idx == old_page + 1
                    and len(xs) == len(old_xs)
                    and all(abs(a - b) <= 4 for a, b in zip(xs, old_xs))
                ):
                    schema = old
            if schema is None:
                continue
            carry = schema, xs, page_idx
            logger.info(
                "Cell-owned %s on PDF page %s: %s data rows",
                schema.table_id,
                page_idx + 1,
                len(ys) - 1 - first_row,
            )
            for ri in range(first_row, len(ys) - 1):
                for pair in range(schema.pairs):
                    start = pair * (1 + len(schema.keys))
                    cells = []
                    for offset, kind in enumerate(("id", *schema.kinds)):
                        ci = start + offset
                        cells.append(
                            read_cell(
                                page,
                                (xs[ci], ys[ri], xs[ci + 1], ys[ri + 1]),
                                tokens,
                                kind,
                                native,
                            )
                        )
                    if all(
                        not c.value and not c.observations[0]["text"] for c in cells
                    ):
                        # An unused last pair is not a silently dropped data row.
                        image = cell_image(page, cells[0].bounds, 150)
                        if (
                            cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) < 160
                        ).mean() < 0.001:
                            continue
                    if not cells[0].value:
                        raise RuntimeError(
                            f"Unresolved compound ID in {schema.table_id}, PDF page {page_idx + 1}, row {ri + 1}, pair {pair + 1}"
                        )
                    values = dict(zip(schema.keys, (c.value for c in cells[1:])))
                    needs_review = any(c.needs_review for c in cells)
                    evidence = {
                        "page_no": page_idx + 1,
                        "table_id": schema.table_id,
                        "target": schema.target,
                        "assay": schema.assay,
                        "cell_line": schema.cell_line,
                        "row": ri,
                        "pair": pair,
                        "cells": [
                            {
                                "field": key,
                                "value": c.value,
                                "bbox": list(c.bounds),
                                "observations": c.observations,
                            }
                            for key, c in zip(("compound_id", *schema.keys), cells)
                        ],
                    }
                    records.append(
                        BiologyRecord(
                            f"Compound {cells[0].value}",
                            values,
                            page_idx + 1,
                            schema.table_id,
                            evidence,
                            needs_review,
                            "Ambiguous cell observations require review."
                            if needs_review
                            else "Cell-owned source geometry; scanned values independently verified.",
                        )
                    )
    return records
