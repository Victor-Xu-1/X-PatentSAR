"""One bounded image-presentation retry; never a competing chemistry source."""

from __future__ import annotations

from pathlib import Path

from .image_preprocess import preprocess_structure_image
from .smiles_cache import compute_image_sha256


def normalized_retry_image(image: str, directory: str) -> str | None:
    source_hash = compute_image_sha256(image)
    target = Path(directory) / "retry" / source_hash
    alternate = preprocess_structure_image(
        image, str(target), padding=30, long_edge=1024
    )
    if alternate == image or not Path(alternate).is_file():
        raise ValueError("Normalized retry input could not be generated")
    return alternate if compute_image_sha256(alternate) != source_hash else None
