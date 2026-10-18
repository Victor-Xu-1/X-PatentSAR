"""Controlled original-image QC records without a Web test-client dependency."""

import hashlib
from pathlib import Path

from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
from patent_sar_extractor.core.ocsr.stereo_evidence import (
    observe_stereo_symbols,
    source_checked_qc,
)


def observation(binding, raw="CCO"):
    image = Path(binding["image_path"])
    checked = source_checked_qc(qc_smiles(raw), observe_stereo_symbols(image))
    return {
        **checked,
        "cpd_id": binding["cpd"],
        "structure_id": binding["structure_id"],
        "raw_smiles": raw,
        "image_hash": hashlib.sha256(image.read_bytes()).hexdigest(),
        "ocsr_original_input": str(image),
        "source_image_path": str(image),
        "OCSR_quality_flag": checked["quality_flag"],
        "OCSR_status": "success"
        if checked["quality_flag"] == "ok"
        else "review_required",
        "model_fingerprint": "a" * 64,
    }
