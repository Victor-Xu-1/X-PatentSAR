"""Transport completed segmentation batches through the existing checkpoint copy."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from patent_sar_extractor import contracts as core

from .attempts import MAX_COPY_FILES
from .errors import WebError
from .processes import RunSpec

if TYPE_CHECKING:
    from .attempts import CheckpointCopy

logger = logging.getLogger(__name__)


def seed_structure_chunks(copy: CheckpointCopy, spec: RunSpec) -> None:
    chunks = copy.source / "structures/.chunks"
    if any(path.is_symlink() for path in (chunks, chunks.parent)):
        raise WebError(
            409,
            "unsafe_checkpoint",
            "Chunk checkpoint directory must not be a symlink.",
        )
    if not chunks.exists():
        return
    locator = copy.files.json("structure_pages/locator.json")
    pages = locator.get("selected_pages") if isinstance(locator, dict) else None
    if (
        not isinstance(pages, list)
        or len(pages) > 10000
        or any(type(page) is not int or not 0 <= page < 10000 for page in pages)
        or len(set(pages)) != len(pages)
    ):
        raise WebError(
            422,
            "invalid_checkpoint",
            "Chunk checkpoints need a validated locator page partition.",
        )
    entries = []
    for scanned, entry in enumerate(chunks.iterdir(), start=1):
        if scanned > MAX_COPY_FILES:
            raise WebError(
                413, "checkpoint_limit", "Chunk directory scan exceeds its bound."
            )
        if not re.fullmatch(r"chunk_[0-9]{3,4}", entry.name):
            continue  # Unpublished temporary files are retained, not transported.
        if entry.is_symlink() or not entry.is_dir():
            raise WebError(
                409, "unsafe_checkpoint", "Chunk checkpoint is not an owned directory."
            )
        entries.append(entry)
        if len(entries) > 10000:
            raise WebError(
                413, "checkpoint_limit", "Chunk checkpoint count exceeds its bound."
            )
    for entry in sorted(entries):
        relative = str((entry / "metadata.json").relative_to(copy.source))
        verified = copy.verify("structures", spec, chunk_path=relative)
        if verified is None:
            logger.info(
                "Incomplete/incompatible segmentation batch was not transported: %s",
                entry.name,
            )
            continue
        params = verified.manifest["fingerprint"]["params"]
        size = params.get("structure_chunk_size")
        index = params.get("chunk_index")
        if (
            type(size) is not int
            or not 1 <= size <= 20
            or type(index) is not int
            or index != int(entry.name[6:])
        ):
            logger.info(
                "Unproved segmentation batch partition was not transported: %s",
                entry.name,
            )
            continue
        expected = pages[index * size : (index + 1) * size]
        if (
            not expected
            or params.get("chunk_pages") != expected
            or any(type(page) is not int for page in params.get("chunk_pages", []))
            or params.get("crop_regions") != locator.get("crop_regions", {})
            or params.get("structure_worker_contract_version")
            != core.STRUCTURE_WORKER_VERSION
        ):
            logger.info(
                "Changed segmentation batch inputs were not transported: %s", entry.name
            )
            continue
        # The existing bounded copier validates image paths, relocates only
        # declared fields and rebases dependency hashes. No whole-stage success
        # or old acceptance/history is created. The CLI rechecks fingerprints.
        copy.checkpoint(verified)
