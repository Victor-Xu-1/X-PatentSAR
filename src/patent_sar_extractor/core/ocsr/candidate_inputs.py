"""Compose the one raw/proved source plan from this job's immutable inputs."""

from pathlib import Path

from patent_sar_extractor.artifact_io import load_json

from .candidate_inventory import asset_digest
from .candidate_observations import build_candidate_plan


def load_source_observation_plan(
    proven, *, structures_json, pdf_path, binding_dir, binding_pdf_sha256
):
    original_sha = asset_digest(pdf_path)
    if not original_sha or binding_pdf_sha256 not in ("", original_sha):
        raise ValueError("Recognition inputs belong to another original document")
    source = Path(structures_json)
    plan = build_candidate_plan(
        load_json(str(source), {}),
        load_json(str(source) + ".manifest.json", {}),
        proven,
        original_pdf_sha256=original_sha,
        metadata_dir=source.resolve().parent,
        binding_dir=binding_dir,
    )
    from ..binding_original_replay import (
        original_binding_source_errors,
        original_binding_sources,
    )

    if original_binding_sources(plan.proven.work_items):
        import fitz

        with fitz.open(pdf_path) as document:
            errors = original_binding_source_errors(document, plan.proven.work_items)
        if errors:
            raise ValueError(
                "Original binding/source replay failed: " + "; ".join(errors[:3])
            )
    return plan
