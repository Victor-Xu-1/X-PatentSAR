"""Explicit model-path adapter around the one official DECIMER MaskRCNN engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from patent_sar_extractor.workers.environment_files import file_sha256

SEGMENTATION_SHA256 = "329120facb69e88add819a3216db0fbfef57e9a37d6b6db0f6149819a11d46a5"


def configure_segmentation_model(model_path: str | Path) -> Any:
    """Use upstream's own cache/consumer, without modifying an installed env.

    Call in the existing isolated extraction subprocess before get_model().
    The parent selects the model path from its captured configuration; there is
    no HTTP path input, alternative architecture, download or automatic fallback.
    """
    path = Path(model_path)
    if (
        any(p.is_symlink() for p in (path, *path.parents))
        or file_sha256(path) != SEGMENTATION_SHA256
    ):
        raise ValueError("Segmentation model content is missing, unsafe or unreviewed")
    import tensorflow as tf
    from decimer_segmentation import decimer_segmentation as upstream

    tf.config.set_visible_devices([], "GPU")
    with tf.device("/CPU:0"):
        model = upstream.modellib.MaskRCNN(
            mode="inference", model_dir=".", config=upstream.InferenceConfig()
        )
        model.load_weights(str(path), by_name=True)
    upstream._model = model
    return upstream.get_model()
