"""Independent SAR startup/readiness; a SAR fault never takes down PDF work."""

from __future__ import annotations

import logging
import sqlite3

from ..errors import WebError
from ..service import WorkspaceService
from .queue import SARQueue
from .service import SARService

logger = logging.getLogger(__name__)


class SARFeature:
    def __init__(self, workspace: WorkspaceService):
        self.workspace = workspace
        self.service: SARService | None = None
        self.queue: SARQueue | None = None
        self.available = False

    def start(self) -> None:
        try:
            self.service = SARService(self.workspace)
            from .migration import recover_legacy_inputs, recover_preparing_uploads

            recover_legacy_inputs(self.service.store, self.service.assets)
            recover_preparing_uploads(self.service.store)
            self.queue = SARQueue(self.service)
            self.queue.start()
            self.available = True
        except (
            WebError,
            OSError,
            sqlite3.Error,
            ValueError,
            RuntimeError,
            KeyError,
            TypeError,
        ) as error:
            logger.error("SAR startup unavailable (%s)", type(error).__name__)
            self.available = False

    def require(self) -> tuple[SARService, SARQueue]:
        if (
            not self.available
            or self.service is None
            or self.queue is None
            or not self.queue.thread
            or not self.queue.thread.is_alive()
        ):
            raise WebError(
                503,
                "sar_unavailable",
                "SAR module is unavailable; PDF extraction is unaffected.",
            )
        return self.service, self.queue

    def close(self) -> None:
        self.available = False
        if self.queue:
            self.queue.close()
