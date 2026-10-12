"""Stopped synthetic history state only; no CLI, model or environment execution."""

from __future__ import annotations

import json
from pathlib import Path

from patent_sar_extractor.web.environment_models import COMPONENT_IDS
from patent_sar_extractor.web.environment_storage import EnvironmentStore
from patent_sar_extractor.web.history_service import HistoryService
from patent_sar_extractor.web.prediction_jobs import enqueue_prediction
from patent_sar_extractor.web.saved_exports import save_export
from patent_sar_extractor.web.storage import Store, encode, now


def prepare_trash(state: Path, project_id: str) -> dict[str, str]:
    store = Store(state)
    # The queue/app has not started. Valid native specs are marked terminal in
    # the same transaction, so no SDK/worker can observe runnable fixture work.
    with store.connect(write=True) as connection:
        for _ in range(101):
            identifier = enqueue_prediction(store, connection, project_id)
            connection.execute(
                "UPDATE jobs SET status='failed',finished_at=?,error='Controlled stopped history fixture; no model run' WHERE id=?",
                (now(), identifier),
            )
            if _ == 0:
                spec = json.loads(
                    connection.execute(
                        "SELECT spec FROM jobs WHERE id=?", (identifier,)
                    ).fetchone()[0]
                )
                product = Path(spec["output_dir"]) / "controlled-output.json"
                product.write_bytes(
                    b"Controlled isolated cleanup product; no model run\n"
                )
    saved = save_export(
        store, project_id, "csv", [b"Controlled retained export; not scientific data\n"]
    )
    environment = EnvironmentStore(state, state.parent / "managed-history")
    spec = {
        "schema_version": 1,
        "requires_owner_ack": True,
        "action": "inspect",
        "component_ids": ["base"],
        "install_root": str(state.parent / "managed-history"),
        "bindings": dict.fromkeys(COMPONENT_IDS),
        "cache_root": str(state / "environments/downloads"),
        "config_fingerprint": "a" * 64,
        "source_key": "b" * 64,
    }
    operation, _ = environment.enqueue(
        "controlled-trash-clear-fixture", "c" * 64, spec, 0
    )
    environment.update(
        operation.id,
        status="cancelled",
        finished_at=now(),
        log_tail=encode(["Controlled history fixture; no installation/inspection"]),
    )
    history = HistoryService(store)
    original = store.locations.pdf_path(store.project(project_id))
    entry = history.get("environment_operation", operation.id)
    history.delete(entry.kind, entry.id, entry.revision)
    entry = history.get("project", project_id)
    history.delete(entry.kind, entry.id, entry.revision)
    assert history.trash_plan().total == 104
    return {
        "PATENTSAR_E2E_HISTORY_MUTATIONS": "synthetic-isolated-state",
        "PATENTSAR_E2E_TRASH_CLEAR_RECORDS": "104",
        "PATENTSAR_E2E_TRASH_FILE_PROOF": json.dumps(
            {
                "delete": [str(original), str(product), str(saved.path)],
                "retain": [
                    str(state.parent / "controlled-native.pdf"),
                    str(state.parent / "controlled-history"),
                    str(state.parent / "controlled-trash-native.pdf"),
                    str(state.parent / "controlled-trash-history"),
                ],
            }
        ),
    }
