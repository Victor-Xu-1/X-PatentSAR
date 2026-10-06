"""Preserve observations; confidence never chooses a winning measurement."""

from __future__ import annotations

import re
from dataclasses import replace

from .activity_identity import is_value, normalize_compound
from .activity_models import ActivityRow, OCRFixRule
from .activity_values import is_explicit_missing_activity_value

# Default lexical parsing never substitutes digits, thresholds or identities.
DEFAULT_OCR_FIXES: list[OCRFixRule] = []


def has_usable_values(row: ActivityRow) -> bool:
    return any(
        str(value or "").strip() and not is_explicit_missing_activity_value(value)
        for bucket in (row.activity_values, row.cell_line_data)
        for value in bucket.values()
    )


def validate_rows(rows: list[ActivityRow]) -> None:
    for row in rows:
        values = [
            v for b in (row.activity_values, row.cell_line_data) for v in b.values()
        ]
        row.needs_review |= not values or any(not is_value(v) for v in values)
        row.needs_review |= any(
            "unknown" in key.lower()
            for bucket in (row.activity_values, row.cell_line_data)
            for key in bucket
        )
        if row.needs_review:
            row.confidence = min(row.confidence, 0.5)


def apply_ocr_fixes(
    row: ActivityRow, rules: list[OCRFixRule], max_cpd_num: int = 0
) -> ActivityRow:
    """Only explicit value rules may edit; original cell observations stay intact."""
    del max_cpd_num  # A maximum cannot prove where an ID or value was split.
    for rule in rules:
        if rule.field == "cpd" or rule.condition:
            raise ValueError(
                "Activity ID/conditional inference is not an evidence-based correction"
            )
        for key, value in list(row.activity_values.items()):
            if rule.field not in {"any", key} and rule.field.lower() not in key.lower():
                continue
            new = (
                re.sub(rule.pattern, rule.replacement, value)
                if rule.is_regex
                else (rule.replacement if value == rule.pattern else value)
            )
            if new != value:
                row.notes += f"; configured OCR correction {rule.name}: {key} {value!r} -> {new!r}"
                row.activity_values[key] = new
                row.needs_review = True
    return row


def merge_rows(rows: list[ActivityRow]) -> list[ActivityRow]:
    """Combine disjoint fields only. Repeated field observations stay as rows.

    The public artifact uses scalar dictionaries. Multiple rows are its existing
    lossless representation for repeated measurements, including equal values.
    """
    output: list[ActivityRow] = []
    by_compound: dict[str, list[ActivityRow]] = {}
    for _, incoming in sorted(
        enumerate(rows),
        key=lambda item: (
            item[1].page_no <= 0,
            item[1].page_no if item[1].page_no > 0 else 10**9,
            item[0],
        ),
    ):
        compound = normalize_compound(incoming.cpd)
        if not compound:
            raise ValueError(f"Unproved activity compound identifier: {incoming.cpd!r}")
        row = replace(
            incoming,
            cpd=compound,
            activity_values=dict(incoming.activity_values),
            cell_line_data=dict(incoming.cell_line_data),
            activity_sources=list(incoming.activity_sources),
        )
        target = next(
            (
                candidate
                for candidate in by_compound.get(compound, [])
                if not (candidate.activity_values.keys() & row.activity_values.keys())
                and not (candidate.cell_line_data.keys() & row.cell_line_data.keys())
            ),
            None,
        )
        if target is None:
            output.append(row)
            by_compound.setdefault(compound, []).append(row)
            continue
        target.activity_values.update(row.activity_values)
        target.cell_line_data.update(row.cell_line_data)
        target.activity_sources.extend(row.activity_sources)
        target.confidence = min(target.confidence, row.confidence)
        target.needs_review |= row.needs_review
        target.table_id = "/".join(
            dict.fromkeys(filter(None, (target.table_id, row.table_id)))
        )
        target.source = "+".join(
            dict.fromkeys(filter(None, (target.source, row.source)))
        )
        target.notes = "; ".join(dict.fromkeys(filter(None, (target.notes, row.notes))))
    return output
