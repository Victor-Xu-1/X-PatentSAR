"""Column-mapped wide and native long CSV datasets, preserving all observations."""

from __future__ import annotations

import json
import re
import time

from ..errors import WebError
from .csv_reader import parse_csv
from .input_records import (
    InputBudget,
    check_deadline,
    merge_identical,
    metric_key,
    molecule_record,
)
from .models import CSVMapping, Metric, Molecule, Observation
from .research_inputs import csv_evidence, validate_mapping


def clean_optional(value: str | None, limit: int = 1000) -> str | None:
    if value is None or not value.strip():
        return None
    if len(value) > limit or any(
        ord(char) < 32 and char not in "\t\r\n" for char in value
    ):
        raise WebError(
            422, "sar_csv_cell", "A mapped CSV cell is invalid or exceeds its limit."
        )
    return value


def mapped_inputs(
    data: bytes, mapping: CSVMapping
) -> tuple[list[Molecule], list[Metric], int]:
    headers, rows = parse_csv(data)
    validate_mapping(mapping, headers)
    context_columns = (
        mapping.assay_column,
        mapping.target_column,
        mapping.unit_column,
        mapping.cell_line_column,
        mapping.duration_column,
        mapping.metric_column,
        mapping.source_page_column,
    )
    selected = [
        mapping.id_column,
        mapping.smiles_column,
        *mapping.activity_columns,
        *(value for value in context_columns if value),
    ]
    if any(value not in headers for value in selected) or len(
        set(mapping.activity_columns)
    ) != len(mapping.activity_columns):
        raise WebError(
            422,
            "sar_csv_mapping",
            "Column mapping must refer to existing distinct CSV columns.",
        )
    if mapping.id_column == mapping.smiles_column or any(
        column in {mapping.id_column, mapping.smiles_column}
        for column in mapping.activity_columns
    ):
        raise WebError(
            422,
            "sar_csv_mapping",
            "Identifier, SMILES and activity roles must be distinct.",
        )
    if mapping.metric_column and len(mapping.activity_columns) != 1:
        raise WebError(
            422,
            "sar_csv_mapping",
            "A long-format metric-name column requires one value column.",
        )
    native = {
        "review_only",
        "acceptance_state",
        "compound_id",
        "smiles",
        "metric",
        "value",
        "structure_molfile_json",
    }.issubset(headers)
    started = time.monotonic()
    records = []
    metrics: dict[str, Metric] = {}
    observations_used = 0
    budget = InputBudget()
    for ordinal, row in enumerate(rows, 1):
        check_deadline(started)
        page_column = mapping.source_page_column or ("source_page" if native else None)
        source_page = None
        if page_column and row.get(page_column, "").strip():
            raw_page = row[page_column].strip()
            if (
                not re.fullmatch(r"[0-9]{1,5}", raw_page)
                or not 1 <= int(raw_page) <= 20000
            ):
                raise WebError(
                    422,
                    "sar_csv_page",
                    "Original PDF page must be an integer from 1 to 20000.",
                )
            source_page = int(raw_page)
        if len(row[mapping.id_column]) > 200 or len(row[mapping.smiles_column]) > 8192:
            raise WebError(
                413,
                "sar_csv_cell",
                "Mapped identifier or SMILES exceeds its explicit SAR limit; no data was truncated.",
            )
        context = {
            key: clean_optional(row.get(column)) if column else None
            for key, column in (
                ("target", mapping.target_column),
                ("assay", mapping.assay_column),
                ("cell_line", mapping.cell_line_column),
                ("duration", mapping.duration_column),
            )
        }
        declared_unit = (
            clean_optional(row.get(mapping.unit_column))
            if mapping.unit_column
            else None
        )
        observations = []
        for column in mapping.activity_columns:
            name = (
                clean_optional(row.get(mapping.metric_column), 300)
                if mapping.metric_column
                else column
            )
            if name is None:
                if row[column].strip():
                    raise WebError(
                        422, "sar_csv_metric", "An activity value has no metric name."
                    )
                continue  # Native structure-only rows remain molecules without measurements.
            unit = declared_unit
            if not unit:
                suffix = re.search(r"\(([^()]{1,100})\)\s*$", name)
                unit = suffix.group(1) if suffix else None
            key = metric_key(name, unit, context["target"], context["assay"])
            metrics.setdefault(
                key,
                Metric(
                    id=key,
                    name=name,
                    unit=unit,
                    target=context["target"],
                    assay=context["assay"],
                ),
            )
            value = row[column]
            if len(value) > 1000:
                raise WebError(
                    413,
                    "sar_observation_limit",
                    "Activity text exceeds its limit; no records were truncated.",
                )
            # Native CSV has a documented spreadsheet escape. The exact original
            # bytes stay SHA-bound in upload storage; generic CSV is never unescaped.
            if (
                native
                and value.startswith("'")
                and value[1:].lstrip().startswith(("=", "+", "-", "@"))
            ):
                value = value[1:]
            observations.append(
                Observation(
                    metric_id=key,
                    value=value,
                    unit=unit,
                    context=context,
                    source_row=ordinal,
                    source_page=source_page,
                    source_kind="imported",
                )
            )
            observations_used += 1
        if len(metrics) > 1000 or observations_used > 100000:
            raise WebError(
                413,
                "sar_observation_limit",
                "SAR exceeds 1000 contexts or 100000 observations; none were truncated.",
            )
        molfile = None
        if native and row.get("structure_molfile_json"):
            try:
                molfile = json.loads(row["structure_molfile_json"])
                if molfile is not None and not isinstance(molfile, str):
                    raise ValueError("invalid")
            except (ValueError, RecursionError) as error:
                raise WebError(
                    422,
                    "sar_csv_structure",
                    "Native CSV molecular representation is invalid.",
                ) from error
        record = molecule_record(
            ordinal,
            row[mapping.id_column],
            row[mapping.smiles_column] or None,
            observations,
            molfile,
            source_page=source_page,
            **csv_evidence(row, mapping),
        )
        budget.add(record[0])
        records.append(record)
    return merge_identical(records), list(metrics.values()), len(rows)
