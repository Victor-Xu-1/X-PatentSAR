"""Release this sequential worker's completed document resources before OCSR.

No process is stopped, model budget lowered, input cache deleted or OCR engine
initialized. Call only after the document/binding handler and its pools returned.
"""

from __future__ import annotations

import ctypes
import gc
import logging
import sys
from pathlib import Path
from typing import Protocol, TypedDict, cast

logger = logging.getLogger(__name__)


class DocumentResourceRelease(TypedDict):
    released_ocr_runtimes: int
    pdf_cache_trimmed: bool
    allocator_trimmed: bool
    rss_before_mb: float | None
    rss_after_mb: float | None


class _OcrOwner(Protocol):
    _OCR_ENGINE: object


def _rss_mb() -> float | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _trim_allocator() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        trim = ctypes.CDLL(None).malloc_trim
    except (OSError, AttributeError):
        return False
    trim.argtypes = [ctypes.c_size_t]
    trim.restype = ctypes.c_int
    return bool(trim(0))


def release_completed_document_phase() -> DocumentResourceRelease:
    before = _rss_mb()
    released = set()
    # Profiler can retain an alias to the shared OCR runtime. Both references
    # must be released; clearing only the shared module does not free it.
    for name in (
        "patent_sar_extractor.core.page_ocr_cache",
        "patent_sar_extractor.core.patent_profiler",
    ):
        module = sys.modules.get(name)
        if module is None:
            continue
        if getattr(module, "_OCR_ENGINE", None):
            owner = cast(_OcrOwner, module)
            released.add(id(owner._OCR_ENGINE))
            owner._OCR_ENGINE = None
        local = getattr(module, "_THREAD_OCR", None)
        if local is not None:
            if getattr(local, "engine", None):
                released.add(id(local.engine))
                local.engine = None
            local.initialized = False
    trimmed = False
    pdf = sys.modules.get("fitz") or sys.modules.get("pymupdf")
    if pdf is not None:
        try:
            pdf.TOOLS.store_shrink(100)
            trimmed = True
        except (AttributeError, RuntimeError, ValueError) as exc:
            logger.warning("Owned PDF cache could not be trimmed: %s", exc)
    gc.collect()
    result: DocumentResourceRelease = {
        "released_ocr_runtimes": len(released),
        "pdf_cache_trimmed": trimmed,
        "allocator_trimmed": _trim_allocator(),
        "rss_before_mb": before,
        "rss_after_mb": _rss_mb(),
    }
    logger.info("Completed document-phase resource release: %s", result)
    return result
