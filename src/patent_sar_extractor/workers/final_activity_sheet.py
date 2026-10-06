"""One worksheet for raw per-measurement provenance, not flattened row sources."""

from __future__ import annotations

import json


def write_activity_observations(workbook, rows: list[dict]) -> None:
    if not rows:
        return
    sheet = workbook.create_sheet("Activity Observations")
    sheet.append(
        [
            "Printed ID",
            "Metric",
            "Value",
            "Page",
            "Table",
            "Target",
            "Assay",
            "Original cell evidence",
        ]
    )
    for row in rows:
        for bucket in ("activity_values", "cell_line_data"):
            for field, value in row.get(bucket, {}).items():
                matching = [
                    source
                    for source in row.get("activity_sources", [])
                    if any(
                        cell.get("field") == field and cell.get("value") == value
                        for cell in source.get("cells", [])
                    )
                ]
                for source in matching or [{}]:
                    sheet.append(
                        [
                            row["cpd"],
                            field,
                            value,
                            source.get("page_no", row.get("page_no")),
                            source.get("table_id", row.get("table_id")),
                            source.get("target"),
                            source.get("assay"),
                            json.dumps(source, ensure_ascii=False) if source else "",
                        ]
                    )
    # Patent/OCR text stays text; no source field can execute a spreadsheet formula.
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
