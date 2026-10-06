"""Validate a bounded chunk window and reuse one verified segmentation model."""

import json
from pathlib import Path


def execute_window(
    extract, plan_path: str, pdf: str, root: str, crop_regions: str, patent_id
):
    output_root = Path(root).resolve()
    plan = Path(plan_path)
    if plan.is_symlink() or plan.stat().st_size > 32768:
        raise ValueError("Segmentation window plan is unsafe or too large")
    payload = json.loads(plan.read_text())
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "jobs"}
        or payload["schema"] != {"name": "patentsar.segmentation-window", "version": 1}
        or not isinstance(payload["jobs"], list)
        or not 1 <= len(payload["jobs"]) <= 3
    ):
        raise ValueError("Segmentation window is outside its reviewed bounds")
    seen_pages, seen_outputs = set(), set()
    jobs = []
    for job in payload["jobs"]:
        if not isinstance(job, dict) or set(job) != {"pages", "output"}:
            raise ValueError("Invalid segmentation job")
        pages, out = job["pages"], Path(job["output"])
        if (
            not isinstance(pages, list)
            or not 1 <= len(pages) <= 20
            or any(type(p) is not int or not 0 <= p <= 20000 for p in pages)
            or len(set(pages)) != len(pages)
            or seen_pages.intersection(pages)
            or not out.is_absolute()
            or out.resolve() == output_root
            or not out.resolve().is_relative_to(output_root)
            or any(p.is_symlink() for p in (out, *out.parents))
            or out in seen_outputs
        ):
            raise ValueError(
                "Segmentation jobs must have distinct owned pages and outputs"
            )
        seen_pages.update(pages)
        seen_outputs.add(out)
        jobs.append((pages, str(out)))
    for index, (pages, out) in enumerate(jobs):
        extract(
            pdf,
            pages,
            out,
            crop_regions,
            patent_id=patent_id,
            initialize_model=index == 0,
        )
