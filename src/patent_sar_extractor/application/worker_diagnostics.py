"""Bounded private worker diagnostics, independent from scientific acceptance."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger("patent_sar_extractor")


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n... worker output truncated ...\n"
    available = limit - len(marker)
    head = available // 3
    return text[:head] + marker + text[-(available - head) :]


def worker_error_details(proc: subprocess.CompletedProcess[str], label: str) -> str:
    """Retain traceback endings and log a larger bounded private excerpt once."""
    text = (proc.stderr or "").strip() or (proc.stdout or "").strip()
    if not text:
        text = f"Worker exited {proc.returncode} without diagnostic output."
    logger.error(
        "%s worker exited %s; bounded captured output:\n%s",
        label,
        proc.returncode,
        _bounded(text, 65536),
    )
    return _bounded(text, 1200)
