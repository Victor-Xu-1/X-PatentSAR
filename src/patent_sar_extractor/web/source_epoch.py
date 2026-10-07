"""Derived source-screen currentness, independent of raw observations/job identity.

These predicates do not inspect strokes, repair chemistry or grant acceptance.
The existing strict source gate remains the validation authority.
"""

from __future__ import annotations

from patent_sar_extractor import contracts as core

from .models import Compound

EPOCH_PARAM = "stereo_evidence_version"
EPOCH_MARKER = "source_stereo_epoch"


def record_epoch_current(record: object, *, allow_unavailable: bool = False) -> bool:
    evidence = record.get("stereochemistry") if isinstance(record, dict) else None
    if (
        isinstance(evidence, dict)
        and type(evidence.get("version")) is int
        and evidence["version"] == core.STEREO_EVIDENCE_VERSION
    ):
        return True
    # Preserve explicit failed/unavailable execution in read-only presentation.
    # This exception cannot supply chemistry or pass acceptance/checkpoint reuse.
    return bool(
        allow_unavailable
        and isinstance(record, dict)
        and evidence is None
        and record.get("OCSR_status")
        in {"image_missing", "engine_unavailable", "unavailable"}
        and not record.get("canonical_smiles")
        and not record.get("smiles")
        and record.get("rdkit_valid") is not True
    )


def smiles_epoch_current(payload: object, *, allow_unavailable: bool = False) -> bool:
    if not isinstance(payload, dict):
        return False
    records, sources = payload.get("records"), payload.get("source_records", [])
    return (
        isinstance(records, list)
        and isinstance(sources, list)
        and all(
            record_epoch_current(record, allow_unavailable=allow_unavailable)
            for record in (*records, *sources)
        )
    )


def stale_source_epoch(compound: Compound) -> bool:
    evidence = compound.recognition.stereochemistry
    if evidence is not None:
        return evidence.version != core.STEREO_EVIDENCE_VERSION
    # A historical proved-source projection deliberately exposes no current
    # recognition proof. Its retained molecular text is not inference consent.
    return (
        compound.structure_id is not None
        and compound.recognition.status == "unavailable"
    )
