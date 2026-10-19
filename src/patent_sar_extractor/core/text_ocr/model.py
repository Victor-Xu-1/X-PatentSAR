"""Only the consented local text model; output stays literal and uncalibrated."""

from __future__ import annotations

from pathlib import Path

from patent_sar_extractor.core.ocsr.resource_budget import process_peak_resident_mb

from .identity import model_files, recipe
from .protocol import read_frame, validate_reply


class LiteralTextModel:
    def __init__(self, identity: dict, root: Path):
        self.identity = identity
        self.root = root
        self._model = None

    def observe(self, request: dict) -> dict:
        # Validate exact owned row before loading the model or running inference.
        image = read_frame(request, self.root, self.identity["fingerprint"])
        if self._model is None:
            directory = Path(self.identity["model_directory"])
            model_files(directory, recipe())
            from paddleocr import TextRecognition

            self._model = TextRecognition(
                model_name=self.identity["model_name"],
                model_dir=str(directory),
                device="cpu",
                cpu_threads=2,
                enable_mkldnn=False,
                enable_hpi=False,
            )
        observations = list(
            self._model.predict(input=image[:, :, ::-1].copy(), batch_size=1)
        )
        if len(observations) != 1:
            raise ValueError("Auxiliary text OCR did not return exactly one row")
        observed = observations[0]
        response = {
            key: request[key]
            for key in ("id", "image_sha256", "pixel_sha256", "model_fingerprint")
        }
        response.update(
            status="observed",
            text=observed["rec_text"],
            confidence=observed["rec_score"],
            device="cpu",
            confidence_kind="uncalibrated_model",
            peak_rss_mb=process_peak_resident_mb(),
        )
        return validate_reply(response, request)
