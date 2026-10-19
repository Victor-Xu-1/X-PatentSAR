"""Lazy optional runtime in an explicit producer phase; GET/readback is inert."""

import atexit
import functools
import hashlib
import os
import shutil
import stat
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from patent_sar_extractor.core.env_runner import (
    configured_model_environment,
    get_python,
)
from patent_sar_extractor.paths import state_dir

_PHASE = ContextVar("auxiliary_text_producer_phase", default=None)
_LOCK = threading.Lock()
_OWNER = None
_OWNER_PHASE = None
_SETTINGS = None


def text_ocr_policy_identity():
    """Task cache selection without importing an SDK or starting any model."""
    selected = configured_model_environment()
    mode = selected.get("PATENTSAR_TEXT_OCR_MODE", "off")
    if mode == "off":
        return {"mode": "off"}
    if mode != "on_demand":
        raise ValueError("Unknown auxiliary text OCR mode")
    from .identity import RESOURCES, model_files, recipe

    models = Path(selected.get("PATENTSAR_TEXT_OCR_MODEL_DIR", ""))
    return {
        "mode": mode,
        "python": get_python("paddleocr"),
        "model_directory": str(models),
        "models": model_files(models, recipe()),
        "recipes": {
            name: hashlib.sha256((RESOURCES / name).read_bytes()).hexdigest()
            for name in ("text-ocr-runtime.json", "text-ocr-sdk.json")
        },
    }


def get_auxiliary_text_runtime():
    global _OWNER, _OWNER_PHASE, _SETTINGS
    phase = _PHASE.get()
    if phase is None:
        return None  # Viewing originals/artifacts never imports or loads an SDK.
    selected = configured_model_environment()
    mode = selected.get("PATENTSAR_TEXT_OCR_MODE", "off")
    if mode == "off":
        with _LOCK:
            if _OWNER_PHASE == phase:
                raise RuntimeError(
                    "Auxiliary text OCR configuration changed during an active phase"
                )
        return None
    if mode != "on_demand":
        raise ValueError("Unknown auxiliary text OCR mode")
    configured = get_python("paddleocr")
    python = Path(
        configured if Path(configured).is_absolute() else shutil.which(configured) or ""
    )
    models = Path(selected.get("PATENTSAR_TEXT_OCR_MODEL_DIR", ""))
    settings = str(python), str(models), str(state_dir())
    with _LOCK:
        if _OWNER is not None:
            if _OWNER_PHASE != phase or _SETTINGS != settings:
                raise RuntimeError(
                    "Auxiliary text OCR owner/configuration changed during an active phase"
                )
            return _OWNER
        from .runtime import AuxiliaryTextRuntime

        root = state_dir() / "text-ocr-transient"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = root.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or any(p.is_symlink() for p in (root, *root.parents))
        ):
            raise ValueError("Auxiliary text OCR workspace is not private and owned")
        _OWNER = AuxiliaryTextRuntime(python, models, root)
        _OWNER_PHASE, _SETTINGS = phase, settings
        return _OWNER


def release_auxiliary_text_runtime(*, phase=None):
    global _OWNER, _OWNER_PHASE, _SETTINGS
    with _LOCK:
        if phase is not None and _OWNER_PHASE != phase:
            return  # A refused concurrent producer must not close the actual owner.
        try:
            if _OWNER is not None:
                _OWNER.close()
        finally:
            _OWNER = _OWNER_PHASE = _SETTINGS = None


@contextmanager
def auxiliary_text_phase():
    if _PHASE.get() is not None:
        yield
        return
    phase = uuid.uuid4().hex
    token = _PHASE.set(phase)
    try:
        yield
    finally:
        try:
            release_auxiliary_text_runtime(phase=phase)
        finally:
            _PHASE.reset(token)


def owns_auxiliary_text(function):
    @functools.wraps(function)
    def owned(*args, **kwargs):
        with auxiliary_text_phase():
            return function(*args, **kwargs)

    return owned


atexit.register(release_auxiliary_text_runtime)
