"""Select all proved printed owners, independently of activity membership."""

from __future__ import annotations

from pathlib import Path

from patent_sar_extractor.contracts import MAX_RECOGNITION_SOURCES

from .acceptance import current
from .artifacts import ArtifactView
from .compound_catalog import read_compound_catalog
from .correction_recovery import saved_fields
from .correction_storage import joined_correction
from .errors import WebError
from .files import SafeFiles, records
from .observation_cache import seed_job_cache
from .recognition_storage import crop_digest
from .source_epoch import stale_source_epoch


def completion_inputs(project: dict, rows: dict, compounds: list) -> list[tuple]:
    if not project["run_root"] or not project["pdf_rel"]:
        return []
    root = Path(project["run_root"])
    view = ArtifactView.read(root)
    if not project["sha256"] or project["sha256"] != view.expected_sha256:
        raise WebError(
            422,
            "source_identity",
            "Structure completion requires the verified original PDF.",
        )
    if not current(view.payloads.get("bindings"), "bindings"):
        return []  # Historical review is not consent or current source ownership.
    catalog, _ = read_compound_catalog(
        view.payloads.get("bindings") or {},
        records(view.payloads.get("structures"), "structures"),
    )
    if catalog is None:
        return []  # unproved anonymous crops are not assigned invented compound IDs
    by_id = {str(item.get("cpd") or item.get("compound_id")): item for item in catalog}
    output = []
    total_sources = 0
    for compound in compounds:
        if compound.recognition.status in {
            "valid",
            "invalid",
        } and not stale_source_epoch(compound):
            continue
        row = rows[compound.id]
        saved = joined_correction(row)
        if saved:
            baseline, values = saved_fields(saved)
            if (
                values.smiles != baseline.smiles
                or values.structure_molfile != baseline.structure_molfile
            ):
                continue  # an explicit user graph/blank is never auto-overwritten
        owner = by_id.get(compound.id)
        if not owner or not row["image_path"] or not compound.structure_image_url:
            continue
        total_sources += 1 + len(owner.get("additional_sources", []))
        if total_sources > MAX_RECOGNITION_SOURCES:
            raise WebError(
                413,
                "recognition_source_limit",
                "Recognition source collection exceeds its bounded workload.",
            )
        if owner.get("structure_id") != compound.structure_id:
            raise WebError(
                422,
                "recognition_owner",
                "Printed identifier no longer owns the table structure.",
            )
        files = SafeFiles(root)
        if files.relative(owner.get("image_path") or "") != files.relative(
            row["image_path"]
        ):
            raise WebError(
                422,
                "recognition_owner",
                "Printed identifier points to another structure image.",
            )
        crop = crop_digest(root, row["image_path"])
        # The converter only sees the same approved bounded crop; no foreign
        # source/alternate path from an imported packet is passed to the engine.
        image = str(root / files.relative(row["image_path"]))
        binding = {
            **owner,
            "cpd": compound.id,
            "image_path": image,
            "source_image_path": image,
            "ocsr_image_path": image,
        }
        additional = []
        for source in owner.get("additional_sources", []):
            original = str(root / files.relative(source.get("image_path") or ""))
            digest = crop_digest(root, original)
            additional.append(
                {
                    **source,
                    "cpd": compound.id,
                    "image_path": original,
                    "source_image_path": original,
                    "ocsr_image_path": original,
                    "_completion_source_sha256": digest,
                }
            )
        binding["additional_sources"] = additional
        output.append((compound.id, binding, crop))
    return output


def seed_observations(project: dict, destination: Path, *, state: Path) -> None:
    """Copy only raw model observations; old acceptance is never transported."""
    seed_job_cache(
        state,
        project,
        destination,
        Path(project["run_root"]) / "smiles/smiles_cache.sqlite",
    )
