"""One bounded owned-process lifecycle for extraction and its subsequent research phase."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .errors import WebError
from .models import Error
from .processes import ProcessIdentity, ProcessRunner, RunSpec
from .storage import Store, encode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhaseResult:
    status: str
    error: Error | None
    cleaned: bool


class OwnedPhase:
    def __init__(
        self, store: Store, runner: ProcessRunner, shutdown: threading.Event
    ) -> None:
        self.store = store
        self.runner = runner
        self.shutdown = shutdown
        self._persisted: dict[str, str] = {}

    def run(
        self,
        spec: RunSpec,
        deadline: float,
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> PhaseResult:
        identity: ProcessIdentity | None = None
        status, error = "failed", None
        phase = "ADMET" if spec.admet_only else "Extraction"
        try:
            if time.monotonic() >= deadline:
                raise WebError(
                    504,
                    "job_timeout",
                    "The task exceeded its configured lifetime before this phase started.",
                )
            if self.shutdown.is_set():
                return PhaseResult(
                    "interrupted",
                    Error(
                        code="server_interrupted",
                        message="Server stopped before the next task phase.",
                    ),
                    True,
                )
            identity = self.runner.start(spec)
            identity.phase = "admet" if spec.admet_only else "extract"
            # Publish identity before the ADMET handshake may load a model.
            self._persist(spec.job_id, identity)
            while True:
                code = self.runner.poll(identity, spec)
                cancel = self._persist(spec.job_id, identity)
                if self.shutdown.is_set():
                    status, error = (
                        "interrupted",
                        Error(
                            code="server_interrupted",
                            message="Server stopped; task checkpoints are preserved.",
                        ),
                    )
                    break
                if cancel:
                    status = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    error = Error(
                        code="job_timeout",
                        message=f"{phase} exceeded the task's configured lifetime.",
                    )
                    break
                if code is not None:
                    status = "complete" if code == 0 else "failed"
                    if code != 0:
                        error = Error(
                            code="admet_failed"
                            if spec.admet_only
                            else "extraction_failed",
                            message=f"Owned {phase} producer exited with status {code}; inspect private run logs.",
                        )
                    break
                if checkpoint is not None:
                    checkpoint()
                self.shutdown.wait(timeout=0.1)
        except Exception as exc:
            logger.exception("Owned task phase failed for %s", spec.job_id)
            error = (
                Error(code=exc.code, message=exc.message)
                if isinstance(exc, WebError)
                else Error(
                    code="job_internal",
                    message="Owned task phase failed at the local process boundary.",
                )
            )
        cleaned = identity is None
        if identity is not None:
            try:
                cleaned = self.runner.stop(identity, spec)
            except Exception:
                logger.exception("Owned phase cleanup failed for %s", spec.job_id)
                cleaned = False
        self._persisted.pop(spec.job_id, None)
        if not cleaned:
            return PhaseResult(
                "interrupted",
                Error(
                    code="ownership_unverified",
                    message="Owned process cleanup could not be verified; resume is disabled.",
                ),
                False,
            )
        return PhaseResult(status, error, True)

    def _persist(self, job_id: str, identity: ProcessIdentity) -> bool:
        encoded = encode(identity.to_dict())
        changed = self._persisted.get(job_id) != encoded
        with self.store.connect(write=changed) as connection:
            if changed:
                connection.execute(
                    "UPDATE jobs SET identity=? WHERE id=? AND status='running'",
                    (encoded, job_id),
                )
            row = connection.execute(
                "SELECT status,cancel_requested,identity FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if row is None or row["status"] != "running":
                raise WebError(
                    409,
                    "job_state_changed",
                    "Task is no longer the active owned producer.",
                )
            if row["identity"] != encoded:
                raise WebError(
                    409,
                    "job_state_changed",
                    "Persisted producer identity changed; no stale process record was reused.",
                )
            cancel = bool(row["cancel_requested"])
        self._persisted[job_id] = encoded
        return cancel
