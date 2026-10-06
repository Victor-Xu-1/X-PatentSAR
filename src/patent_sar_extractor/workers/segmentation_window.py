"""Validate a bounded chunk window and reuse one verified segmentation model."""

import json
from pathlib import Path

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.pipeline_io import _worker_output_state
from patent_sar_extractor.workers.segmentation_checkpoint import (
    seal_chunk,
    verified_input,
)


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
        or payload["schema"]
        != core.schema_ref(
            core.SEGMENTATION_WINDOW_SCHEMA, core.SEGMENTATION_WINDOW_SCHEMA_VERSION
        )
        or not isinstance(payload["jobs"], list)
        or not 1 <= len(payload["jobs"]) <= 3
    ):
        raise ValueError("Segmentation window is outside its reviewed bounds")
    seen_pages, seen_outputs = set(), set()
    jobs = []
    for job in payload["jobs"]:
        if not isinstance(job, dict) or set(job) != {
            "pages",
            "output",
            "fingerprint_file",
        }:
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
        fingerprint = verified_input(
            pdf, output_root, out, pages, job["fingerprint_file"], crop_regions
        )
        jobs.append((pages, str(out), fingerprint, job["fingerprint_file"]))
    for index, (pages, out, fingerprint, input_file) in enumerate(jobs):
        before = _worker_output_state(Path(out) / "metadata.json")
        extract(
            pdf,
            pages,
            out,
            crop_regions,
            patent_id=patent_id,
            initialize_model=index == 0,
        )
        if fingerprint != verified_input(
            pdf, output_root, Path(out), pages, input_file, crop_regions
        ):
            raise ValueError("Segmentation inputs changed while computing a chunk")
        seal_chunk(Path(out), before, fingerprint)
