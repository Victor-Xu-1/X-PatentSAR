"""Small post-primary rescue queue. One candidate, exact graph, original evidence."""

from __future__ import annotations

import re
from pathlib import Path

from .engines.molscribe_engine import MolScribeEngine
from .smiles_cache import compute_image_sha256
from .smiles_qc import qc_smiles
from .stereo_evidence import observe_stereo_symbols, source_checked_qc
from .stereo_rescue import validate_stereo_rescue

RESCUE_VERSION = 1
MAX_RESCUES = 8


class RescueProofRefusal(ValueError):
    """Bounded scientific refusal, distinct from malformed identity/protocol."""


def eligible(record: dict) -> bool:
    evidence = record.get("stereochemistry")
    return (
        record.get("OCSR_engine") == "decimer"
        and record.get("OCSR_status") == "review_required"
        and record.get("OCSR_quality_flag") == "stereochemistry_not_retained"
        and isinstance(evidence, dict)
        and evidence.get("status") == "no_unknown_detected"
        and evidence.get("unknown_bond_boxes") == []
    )


def apply_stereo_rescue(
    results, source_paths, prediction, *, engine_configs, progress, check_cancel=None
):
    indexes = [i for i, result in enumerate(results) if eligible(result)][:MAX_RESCUES]
    if not indexes:
        return results
    engine = MolScribeEngine(**engine_configs.get("molscribe", {}))
    try:
        for index in indexes:
            if check_cancel is not None:
                check_cancel()
            record, source = results[index], source_paths[index]
            if (
                not source
                or not Path(source).is_file()
                or compute_image_sha256(source) != record["image_hash"]
            ):
                record["local_stereo_rescue"] = {
                    "status": "refused",
                    "reason": "source_identity_changed",
                }
                continue
            candidate, notes = prediction("molscribe", engine, source)
            raw = candidate.get("raw_smiles")
            checked = source_checked_qc(qc_smiles(raw), observe_stereo_symbols(source))
            decision = validate_stereo_rescue(
                record.get("raw_smiles"),
                raw,
                primary_quality_flag=record["OCSR_quality_flag"],
            )
            if (
                candidate.get("status") != "success"
                or checked["quality_flag"] != "ok"
                or not decision["accepted"]
            ):
                record["local_stereo_rescue"] = {
                    "status": "refused",
                    "reason": decision["reason"],
                    "candidate_raw_smiles": raw,
                    "candidate_quality_flag": checked["quality_flag"],
                }
                if getattr(engine, "session_exhausted", False):
                    break  # Missing runtime/dead process is not a molecular retry.
                continue
            proof = {
                "version": RESCUE_VERSION,
                "primary_engine": "decimer",
                "primary_raw_smiles": record["raw_smiles"],
                "primary_model_fingerprint": record.get("model_fingerprint"),
                "candidate_model_fingerprint": candidate.get("model_fingerprint"),
                "source_image_sha256": record["image_hash"],
                "decision": decision,
            }
            try:
                validate_rescue_proof(
                    {
                        **record,
                        "raw_smiles": raw,
                        "model_fingerprint": candidate.get("model_fingerprint"),
                        "OCSR_engine": "molscribe",
                        "stereo_rescue_proof": proof,
                    }
                )
            except RescueProofRefusal as refused:
                record["local_stereo_rescue"] = {
                    "status": "refused",
                    "reason": str(refused),
                    "candidate_raw_smiles": raw,
                }
                continue
            prior = dict(record)
            record.update(
                **{
                    key: checked[key]
                    for key in (
                        "canonical_smiles",
                        "inchikey",
                        "mol_formula",
                        "mol_weight",
                        "heavy_atom_count",
                        "ring_count",
                        "chiral_centers",
                        "rdkit_valid",
                        "stereochemistry",
                    )
                },
                raw_smiles=raw,
                engine_raw_smiles=raw,
                OCSR_engine="molscribe",
                OCSR_quality_flag="ok",
                OCSR_status="success",
                OCSR_failure_reason=None,
                ocsr_structure_image=source,
                model_fingerprint=candidate["model_fingerprint"],
                device=candidate.get("device"),
                peak_rss_mb=candidate.get("peak_rss_mb"),
                token_confidence=None,
                model_confidence=candidate.get("model_confidence"),
                stereo_rescue_proof=proof,
            )
            record["engine_attempts"] = [
                *record["engine_attempts"],
                {
                    "engine": "molscribe",
                    "status": "success",
                    "quality_flag": "ok",
                    "raw_smiles": raw,
                    "input_source": "constrained_stereo_rescue",
                    "input_image": source,
                    "model_fingerprint": candidate["model_fingerprint"],
                    "elapsed_sec": candidate.get("elapsed_sec", 0),
                    **notes,
                },
            ]
            progress.replace(prior, record)
    finally:
        engine.close()
    return results


def validate_rescue_proof(record: dict) -> None:
    if record.get("OCSR_engine") != "molscribe":
        if record.get("stereo_rescue_proof") is not None:
            raise ValueError("Local rescue proof belongs to a different native engine")
        return
    proof = record.get("stereo_rescue_proof")
    required = {
        "version",
        "primary_engine",
        "primary_raw_smiles",
        "primary_model_fingerprint",
        "candidate_model_fingerprint",
        "source_image_sha256",
        "decision",
    }
    if (
        not isinstance(proof, dict)
        or set(proof) != required
        or type(proof["version"]) is not int
        or proof["version"] != RESCUE_VERSION
    ):
        raise ValueError("Local rescue proof is missing or invalid")
    if proof["primary_engine"] != "decimer" or proof[
        "source_image_sha256"
    ] != record.get("image_hash"):
        raise ValueError("Local rescue source/primary identity differs")
    for key in ("primary_model_fingerprint", "candidate_model_fingerprint"):
        if not isinstance(proof[key], str) or not re.fullmatch(
            r"[a-f0-9]{64}", proof[key]
        ):
            raise ValueError("Local rescue model identity is invalid")
    if proof["candidate_model_fingerprint"] != record.get("model_fingerprint"):
        raise ValueError("Local rescue candidate fingerprint differs")
    decision = validate_stereo_rescue(
        proof["primary_raw_smiles"],
        record.get("raw_smiles"),
        primary_quality_flag="stereochemistry_not_retained",
    )
    if not decision["accepted"]:
        raise RescueProofRefusal(decision["reason"])
    if proof["decision"] != decision:
        raise ValueError("Local rescue graph/stereo proof does not validate")
