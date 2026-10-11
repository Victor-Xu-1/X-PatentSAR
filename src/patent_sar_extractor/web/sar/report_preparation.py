"""Receipt-checked report preparation; large models live only with active readers."""

from __future__ import annotations

import hashlib
import threading
import weakref
from collections import OrderedDict
from functools import lru_cache

from ..errors import WebError
from .study_models import StudyReport


@lru_cache(maxsize=2)
def _small_report(content: bytes) -> StudyReport:
    # Existing <=4MiB/two-packet retention policy, not a new large result cache.
    return StudyReport.model_validate_json(content)


class ReportPreparation:
    """Share complete read-only validation ONLY while another reader uses it.

    Every caller rechecks its current bytes against the published receipt before
    any reuse. Large packet bytes are not keys or retained values. At most32
    weak metadata entries refer to models; the final reader owns their lifetime.
    The parse lock coalesces concurrent cold reads without partial/failed values.
    Consumers must derive their own mutable current projections, never edit the
    captured model. No scientific validation, size limit or proof is skipped.
    """

    def __init__(self):
        self._large: OrderedDict[
            tuple[str, int], weakref.ReferenceType[StudyReport]
        ] = OrderedDict()
        self._lock = threading.Lock()

    def read(self, content: bytes, expected_sha256: str) -> StudyReport:
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_sha256:
            raise WebError(
                409,
                "sar_report_changed",
                "Study report bytes differ from the complete receipt.",
            )
        if len(content) <= 4 * 1024 * 1024:
            return _small_report(content)
        key = (digest, len(content))
        with self._lock:
            reference = self._large.get(key)
            report = reference() if reference is not None else None
            if report is not None:
                self._large.move_to_end(key)
                return report
            report = StudyReport.model_validate_json(content)
            self._large[key] = weakref.ref(report)
            self._large.move_to_end(key)
            for stale in tuple(self._large):
                if self._large[stale]() is None:
                    del self._large[stale]
            while len(self._large) > 32:
                self._large.popitem(last=False)
            return report


report_preparation = ReportPreparation()
