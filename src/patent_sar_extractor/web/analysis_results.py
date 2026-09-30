"""Validate model/cache responses identically before returning any research result."""

from __future__ import annotations

from pydantic import ValidationError

from patent_sar_extractor.workers.analysis_protocol import ADMET_VERSION

from .analysis_chemistry import canonical_smiles, recognized_smiles
from .analysis_models import ADMETResponse, RecognitionResponse
from .analysis_runtime import ModelBundle
from .errors import WebError
from .models import Compound


def admet_response(
    payload: object, values: list[str], bundle: ModelBundle
) -> ADMETResponse:
    try:
        result = ADMETResponse.model_validate(payload)
        if (
            result.engine.name != "ADMET-AI"
            or result.engine.version != ADMET_VERSION
            or result.engine.model_sha256 != bundle.model_sha256
            or [p.smiles for p in result.predictions] != values
        ):
            raise ValueError("Model identity or molecule order differs")
        for prediction in result.predictions:
            if canonical_smiles(prediction.smiles) != prediction.smiles:
                raise ValueError("Prediction molecule is not canonical")
            if {p.key for p in prediction.properties} != set(bundle.endpoints):
                raise ValueError("Endpoint inventory differs")
            for prop in prediction.properties:
                endpoint = bundle.endpoints[prop.key]
                if (
                    prop.label != endpoint.label
                    or prop.unit != endpoint.unit
                    or prop.kind != endpoint.kind
                    or (endpoint.probability and not 0 <= prop.value <= 1)
                ):
                    raise ValueError("Endpoint semantics differ")
        return result
    except (ValidationError, ValueError, WebError) as exc:
        raise WebError(
            502,
            "analysis_result_invalid",
            "Analysis returned invalid molecules, endpoint metadata or numerical values.",
        ) from exc


def compound(payload: str) -> Compound:
    if len(payload) > 256 * 1024:
        raise WebError(
            413, "evidence_limit", "Stored compound evidence exceeds its size limit."
        )
    try:
        return Compound.model_validate_json(payload)
    except ValidationError as exc:
        raise WebError(
            422,
            "invalid_evidence",
            "Stored compound evidence is malformed or non-finite.",
        ) from exc


def recognition_response(payload: object, compound_id: str) -> RecognitionResponse:
    try:
        result = RecognitionResponse.model_validate(payload)
        if result.compound_id != compound_id or result.engine.name != "DECIMER":
            raise ValueError("Recognition identity differs")
        if (
            result.smiles is not None
            and recognized_smiles(result.smiles) != result.smiles
        ):
            raise ValueError("Recognition cache failed QC")
        return result
    except (ValidationError, ValueError) as exc:
        raise WebError(
            502,
            "analysis_result_invalid",
            "Recognition cache or model result failed identity/QC validation.",
        ) from exc
