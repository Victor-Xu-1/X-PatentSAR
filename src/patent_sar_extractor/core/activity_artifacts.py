"""The single activity artifact writer; original source evidence is serialized."""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    artifact_identity,
)

from .activity_identity import is_control
from .activity_models import ActivityRow
from .activity_observations import has_usable_values


def save_results(
    rows: list[ActivityRow], vlm_results: dict | None, output_dir: Path, profile: dict
) -> None:
    value_keys = list(dict.fromkeys(k for r in rows for k in r.activity_values))
    cell_keys = list(dict.fromkeys(k for r in rows for k in r.cell_line_data))
    fields = [
        "cpd",
        "page_no",
        "table_id",
        "column_side",
        "source",
        "confidence",
        "needs_review",
        "notes",
    ]
    with (output_dir / "activity_data.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields + value_keys + cell_keys)
        writer.writeheader()
        for row in rows:
            record = {key: getattr(row, key) for key in fields}
            record.update({key: row.activity_values.get(key, "") for key in value_keys})
            record.update({key: row.cell_line_data.get(key, "") for key in cell_keys})
            writer.writerow(record)
    active = list(
        dict.fromkeys(
            r.cpd for r in rows if not is_control(r.cpd) and has_usable_values(r)
        )
    )
    write_json_atomic(
        output_dir / "activity_data.json",
        {
            **artifact_identity(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "patent_id": profile.get("patent_id", ""),
                "n_rows": len(rows),
                "n_unique_cpds": len({r.cpd for r in rows}),
                "n_active_cpds": len(active),
            },
            "active_cpds": active,
            "rows": [asdict(row) for row in rows],
        },
    )
    if vlm_results:
        write_json_atomic(output_dir / "vlm_results.json", vlm_results)
    review = [r for r in rows if r.needs_review]
    report = [
        "# Activity Extraction Report",
        "",
        f"Patent: {profile.get('patent_id', '')}",
        "",
        f"- Total original rows: {len(rows)}",
        f"- Unique identifiers: {len({r.cpd for r in rows})}",
        f"- Needs review: {len(review)}",
        "",
    ]
    report.extend(f"- {r.cpd} (p{r.page_no}): {r.activity_values}" for r in review[:20])
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
