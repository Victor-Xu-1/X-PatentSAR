"""Load only verified printed weights with the installed SDK's exact transforms.

The upstream initializer eagerly loads two models and overrides device policy.
Loading its pure support modules by file avoids that initializer; upstream code
is never patched, copied or downloaded.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import pickle
import resource
from pathlib import Path


def _sdk_module(directory: Path, name: str):
    specification = importlib.util.spec_from_file_location(
        f"patentsar_decimer_{name}", directory / f"{name}.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class PrintedDecimerModel:
    def __init__(self, identity: dict):
        from .resource_budget import check_model_headroom

        check_model_headroom()
        import tensorflow as tf

        gpu_enabled = os.environ.get("PATENTSAR_DECIMER_ENABLE_GPU", "0") == "1"
        if not gpu_enabled:
            tf.config.set_visible_devices([], "GPU")
        else:
            devices = tf.config.list_physical_devices("GPU")
            if not devices:
                raise RuntimeError("GPU requested but TensorFlow has no compatible GPU")
            for device in devices:
                tf.config.experimental.set_memory_growth(device, True)
        threads = int(os.environ.get("PATENTSAR_DECIMER_CPU_THREADS", "2"))
        if not 1 <= threads <= 16:
            raise ValueError("DECIMER CPU threads must be between 1 and 16")
        tf.config.threading.set_intra_op_parallelism_threads(threads)
        tf.config.threading.set_inter_op_parallelism_threads(1)
        self.tf = tf
        self.identity = identity
        self.device = "gpu" if gpu_enabled else "cpu"
        sdk = Path(identity["sdk_directory"])
        self.preprocess = _sdk_module(sdk, "pre_process")
        self.codec = _sdk_module(sdk, "utils")
        root = Path(identity["model_directory"])
        # The identity verifies official tokenizer bytes before deserialization.
        with (root / "assets/tokenizer_SMILES.pkl").open("rb") as stream:
            tokenizer_bytes = stream.read(8193)
        if (
            len(tokenizer_bytes) > 8192
            or hashlib.sha256(tokenizer_bytes).hexdigest()
            != identity["tokenizer_sha256"]
        ):
            raise ValueError("DECIMER tokenizer changed after identity verification")
        self.tokenizer = pickle.loads(tokenizer_bytes)
        self.model = tf.saved_model.load(str(root))

    @property
    def peak_rss_mb(self) -> float:
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)

    def predict(self, image: str) -> dict:
        from PIL import Image

        if Path(image).stat().st_size > 16 * 1024 * 1024:
            raise ValueError("OCSR input exceeds the encoded image limit")
        with Image.open(image) as inspected:
            if inspected.width * inspected.height > 25_000_000:
                raise ValueError("OCSR input exceeds the decoded pixel limit")
        processed = self.preprocess.decode_image(image)
        tokens, confidence = self.model(self.tf.constant(processed))
        words = [self.tokenizer.index_word[int(value)] for value in tokens[0].numpy()]
        encoded = "".join(words).replace("<start>", "").replace("<end>", "")
        smiles = self.codec.decoder(encoded)
        if not isinstance(smiles, str) or not smiles.strip() or len(smiles) > 12000:
            raise ValueError("DECIMER returned no bounded nonempty prediction")
        probabilities = [
            float(value)
            for value in self.tf.convert_to_tensor(confidence).numpy().reshape(-1)[1:-1]
        ]
        if probabilities and not all(
            math.isfinite(value) and 0 <= value <= 1 for value in probabilities
        ):
            raise ValueError("DECIMER returned invalid token confidence")
        return {
            "smiles": smiles,
            "model_fingerprint": self.identity["fingerprint"],
            "model_version": self.identity["versions"]["DECIMER"],
            "device": self.device,
            "peak_rss_mb": self.peak_rss_mb,
            "token_confidence": {
                "minimum": min(probabilities),
                "mean": sum(probabilities) / len(probabilities),
            }
            if probabilities
            else None,
        }
