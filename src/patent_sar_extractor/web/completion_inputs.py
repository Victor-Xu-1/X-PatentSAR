"""Select all proved printed owners, independently of activity membership."""

from __future__ import annotations

import os
from pathlib import Path

from patent_sar_extractor.core.ocsr.cache_snapshot import snapshot_observations

from .artifacts import ArtifactView
from .compound_catalog import read_compound_catalog
from .correction_recovery import saved_fields
from .correction_storage import joined_correction
from .errors import WebError
from .files import SafeFiles, records
from .recognition_storage import crop_digest


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
    catalog, _ = read_compound_catalog(
        view.payloads.get("bindings") or {},
        records(view.payloads.get("structures"), "structures"),
    )
    if catalog is None:
        return []  # unproved anonymous crops are not assigned invented compound IDs
    by_id = {str(item.get("cpd") or item.get("compound_id")): item for item in catalog}
    output = []
    for compound in compounds:
        if compound.recognition.status in {"valid", "invalid"}:
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
        output.append((compound.id, binding, crop))
    return output


def seed_observations(project: dict, destination: Path) -> None:
    """Copy only raw model observations; old acceptance is never transported."""
    if destination.exists():
        return
    files = SafeFiles(Path(project["run_root"]))
    try:
        content = files.read("smiles/smiles_cache.sqlite", max_bytes=64 * 1024 * 1024)
    except WebError as exc:
        if exc.code == "asset_unavailable":
            return
        raise
    try:
        snapshot = snapshot_observations(
            content, max_bytes=64 * 1024 * 1024, max_records=25000
        )
    except ValueError as exc:
        raise WebError(
            422, "recognition_cache", "Original raw-observation cache is invalid."
        ) from exc
    fd = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(snapshot)
        stream.flush()
        os.fsync(stream.fileno())
