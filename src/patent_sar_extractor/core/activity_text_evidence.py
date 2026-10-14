"""Original delimited-text row evidence for the sole activity text reader."""

from .activity_metadata import mark_metadata
from .activity_models import TableContext


def text_evidence(
    context: TableContext,
    page_no: int,
    row_index: int,
    label: str,
    keys: list[str],
    values: list[str],
    raw_row: str,
    raw_header: str,
    metadata_headers: dict[int, tuple[str, str]],
) -> dict:
    evidence = {
        "page_no": page_no,
        "table_id": context.table_id,
        "raw_caption": context.raw_caption,
        "target": context.target,
        "assay": context.assay,
        "cell_line": context.cell_line,
        "row": row_index,
        "raw_header": raw_header[:10000],
        "cells": [
            {
                "field": "compound_id",
                "value": label,
                "bbox": None,
                "observations": [
                    {
                        "method": "declared_text_row",
                        "text": label,
                        "raw_text": raw_row[:10000],
                    }
                ],
            },
            *[
                {
                    "field": key,
                    "value": value,
                    "bbox": None,
                    "observations": [
                        {
                            "method": "declared_text_cell",
                            "text": value,
                            "raw_text": raw_row[:10000],
                        }
                    ],
                }
                for key, value in zip(keys, values)
            ],
        ],
    }
    for index, cell in enumerate(evidence["cells"][1:]):
        if index in metadata_headers:
            raw, kind = metadata_headers[index]
            cell.update(raw_header=raw, physical_column=index + 1)
            cell["observations"].append(
                {
                    "method": "declared_text_count_cell",
                    "text": cell["value"],
                    "raw_text": raw_row[:10000],
                }
            )
            evidence["cells"][index + 1] = mark_metadata(cell, kind)
    return evidence
