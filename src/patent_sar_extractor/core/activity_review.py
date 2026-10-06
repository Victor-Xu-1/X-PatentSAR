"""Optional injected review adapter. Model suggestions never replace source cells."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import fitz

from .activity_models import ActivityRow


def review_rows(
    rows: list[ActivityRow],
    pdf_path: str,
    output: Path,
    tables: list[dict],
    api_url: str,
    api_key: str,
    model: str,
    callback: Callable,
) -> dict:
    results = {}
    directory = output / "vlm_images"
    directory.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as doc:
        for page_index in sorted(
            {p for table in tables for p in table.get("pages", [])}
        ):
            path = directory / f"page_{page_index + 1:04d}.png"
            doc[page_index].get_pixmap(matrix=fitz.Matrix(2, 2)).save(path)
            response = callback(
                str(path),
                (
                    "Review the original table. Return a JSON array of {cpd, values}. "
                    "Preserve printed identifiers, raw values, missing cells, units and contexts. "
                    "Do not infer absent values or repair digits, thresholds or IDs."
                ),
                api_url,
                api_key,
                model,
            )
            match = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", response, re.S)
            try:
                parsed = json.loads(match.group(1) if match else response)
            except json.JSONDecodeError as error:
                raise ValueError("Malformed activity review JSON") from error
            if not isinstance(parsed, list) or any(
                not isinstance(item, dict) for item in parsed
            ):
                raise ValueError("Malformed activity review rows")
            results[str(page_index + 1)] = {
                "page_no": page_index + 1,
                "raw_response": response,
                "parsed_rows": parsed,
            }
            for row in rows:
                if not any(
                    s.get("page_no") == page_index + 1 for s in row.activity_sources
                ):
                    continue
                matches = [item for item in parsed if item.get("cpd") == row.cpd]
                if len(matches) != 1 or matches[0].get("values") != row.activity_values:
                    row.needs_review = True
                    row.notes += (
                        "; optional review disagrees with the original observation"
                    )
    return results
