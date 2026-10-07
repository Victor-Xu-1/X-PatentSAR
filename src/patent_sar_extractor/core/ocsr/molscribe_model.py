"""Pinned native inference. Never reinterpret, repair or merge model strings."""

from __future__ import annotations

import contextlib
import math
import resource
import sys
from pathlib import Path


class PinnedMolScribeModel:
    device = "cpu"

    def __init__(self, identity: dict):
        self.identity = identity
        with contextlib.redirect_stdout(sys.stderr):
            import cv2
            import torch
            from molscribe import MolScribe

            torch.set_num_threads(2)
            torch.set_num_interop_threads(1)
            torch.manual_seed(0)
            cv2.setNumThreads(1)
            # The hash-checked checkpoint needs no arbitrary pickle globals.
            states = torch.load(
                identity["model_path"], map_location="cpu", weights_only=True, mmap=True
            )
            self.model = MolScribe(
                identity["model_path"], device=torch.device("cpu"), num_workers=1
            )
            for component in ("encoder", "decoder"):
                declared = {
                    key.replace("module.", ""): value
                    for key, value in states[component].items()
                }
                actual = getattr(self.model, component).state_dict()
                if set(actual) != set(declared) or any(
                    actual[k].shape != declared[k].shape for k in actual
                ):
                    raise ValueError("Local rescue checkpoint keys/shapes differ")

    @property
    def peak_rss_mb(self) -> float:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    def predict(self, image_path: str) -> dict:
        from PIL import Image

        path = Path(image_path)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Rescue image exceeds its byte budget")
        with Image.open(path) as image:
            if image.width * image.height > 16 * 1024 * 1024:
                raise ValueError("Rescue image exceeds its pixel budget")
        with contextlib.redirect_stdout(sys.stderr):
            output = self.model.predict_image_file(str(path), return_confidence=True)
        raw = output.get("smiles")
        observed = output.get("confidence")
        confidence = float(observed) if observed is not None else None
        if not isinstance(raw, str) or not 0 < len(raw) <= 12000:
            raise ValueError("Rescue SDK returned no bounded raw SMILES")
        if confidence is not None and (
            not math.isfinite(confidence) or not 0 <= confidence <= 1
        ):
            raise ValueError("Rescue SDK returned invalid confidence")
        return {
            "smiles": raw,
            "model_fingerprint": self.identity["fingerprint"],
            "model_version": self.identity["adapter_version"],
            "device": "cpu",
            "peak_rss_mb": self.peak_rss_mb,
            "model_confidence": confidence,
        }
