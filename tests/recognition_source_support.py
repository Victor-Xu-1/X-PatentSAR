"""Controlled original-image QC records without a Web test-client dependency."""

import hashlib
from pathlib import Path

from patent_sar_extractor.core.ocsr.recognition_source_paths import (
    resolve_ocsr_image_path,
)
from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import (
    observe_stereo_symbols,
    source_checked_qc,
)


def observation(binding, raw="CCO"):
    image = Path(resolve_ocsr_image_path(binding))
    checked = source_checked_qc(qc_smiles(raw), observe_stereo_symbols(image))
    return {
        **checked,
        "cpd_id": binding["cpd"],
        "structure_id": binding["structure_id"],
        "ocsr_source_structure_id": binding.get("source_structure_id")
        or binding["structure_id"],
        "raw_smiles": raw,
        "image_hash": hashlib.sha256(image.read_bytes()).hexdigest(),
        "ocsr_original_input": str(image),
        "source_image_path": str(image),
        **(
            {"candidate_source_id": binding["candidate_source_id"]}
            if "candidate_source_id" in binding
            else {}
        ),
        "OCSR_engine": "decimer",
        "page_no": binding["page_no"],
        "OCSR_quality_flag": checked["quality_flag"],
        "OCSR_status": "success"
        if checked["quality_flag"] == "ok"
        else "review_required",
        "model_fingerprint": "a" * 64,
    }


def complete_observation_artifact(
    payload, *, pdf, structures, binding_dir, source_raw="CCO"
):
    """Controlled full-input worker output; never an OCSR accuracy claim."""
    from patent_sar_extractor.core.ocsr.candidate_inputs import (
        load_source_observation_plan,
    )
    from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
    from patent_sar_extractor.smiles_artifact import build_smiles_artifact

    plan = load_source_observation_plan(
        recognition_inputs(payload),
        structures_json=structures,
        pdf_path=pdf,
        binding_dir=binding_dir,
        binding_pdf_sha256=payload["source_reference_scope"]["original_pdf_sha256"],
    )
    return build_smiles_artifact(
        [observation(item) for item in plan.proven.formal],
        source_records=[
            observation(item, source_raw) for item in plan.proven.supplemental
        ],
        reprint_records=[observation(item) for item in plan.proven.reprints],
        candidate_records=[observation(item) for item in plan.candidates],
        candidate_inventory=plan.inventory,
    )
