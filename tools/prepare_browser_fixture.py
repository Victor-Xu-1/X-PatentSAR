"""Prepare isolated CI browser data and one real CLI failure, never scientific results."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from patent_sar_extractor.web.app import create_app
from patent_sar_extractor.web.service import import_run
from patent_sar_extractor.web.storage import now


def prepare(workspace: Path) -> dict[str, str]:
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Browser fixture workspace must be empty")
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reuse explicit adapter fixtures rather than adding a production seed route.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_web_support import artifact_run, make_pdf

    pdf = make_pdf(
        workspace / "controlled-native.pdf",
        text="Controlled browser protocol fixture; no chemistry or activity data.",
    )
    run = artifact_run(
        workspace / "controlled-history", pdf, current=False, accepted=False, rows=30
    )
    state = workspace / "web-state"
    historical = import_run(
        state,
        run,
        pdf_path=pdf,
        title="CI controlled historical adapter fixture (not extraction evidence)",
    )
    origin = "http://127.0.0.1:18765"
    with TestClient(
        create_app(state, host="127.0.0.1", port=18765, job_timeout_seconds=90),
        base_url=origin,
    ) as client:
        session = client.get("/api/v1/session")
        session.raise_for_status()
        client.headers.update(
            {"Origin": origin, "X-CSRF-Token": session.json()["csrf_token"]}
        )
        project = client.post(
            "/api/v1/projects?filename=controlled-native.pdf&title=Controlled%20real%20CLI%20failure",
            content=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf"},
        )
        project.raise_for_status()
        request = client.post(f"/api/v1/projects/{project.json()['id']}/jobs", json={})
        request.raise_for_status()
        job_id = request.json()["id"]
        deadline = time.monotonic() + 100
        while True:
            response = client.get(f"/api/v1/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job["status"] not in {"queued", "running"}:
                break
            if time.monotonic() > deadline:
                raise ValueError(
                    "Real controlled CLI job did not finish within its bound"
                )
            time.sleep(0.1)
        if job["status"] != "failed" or not job["error"]:
            raise ValueError(
                "A PDF without chemistry must not become a successful extraction"
            )
        environment_store = client.app.state.environments.store
        settings = environment_store.settings()
        history_operation, _ = environment_store.enqueue(
            "controlled-history-deletion-fixture",
            "controlled-history-deletion-fixture",
            {
                "schema_version": 1,
                "action": "inspect",
                "component_ids": ["installer"],
                "install_root": settings["install_root"],
            },
            settings["revision"],
        )
        # A terminal history fixture, not a real inspection/install or readiness
        # claim. No environment reports/configuration/model are populated.
        environment_store.update(
            history_operation.id,
            status="cancelled",
            finished_at=now(),
            stage="Controlled history fixture; no installation or inspection",
        )
    values = {
        "PATENTSAR_WEB_STATE_DIR": str(state),
        "PATENTSAR_E2E_PDF": str(pdf),
        "PATENTSAR_E2E_HISTORY_PROJECT_ID": historical.id,
        "PATENTSAR_E2E_FAILED_JOB_ID": job_id,
        "PATENTSAR_E2E_ENVIRONMENT_OPERATION_ID": history_operation.id,
        "PATENTSAR_E2E_RUN_JOBS": "1",
    }
    (workspace / "browser-fixture.json").write_text(
        json.dumps(
            {
                "controlled_adapter_fixture": True,
                "scientific_acceptance_evidence": False,
                "real_cli_failure": True,
                **values,
            },
            indent=2,
        )
        + "\n"
    )
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--github-env", action="store_true")
    args = parser.parse_args()
    values = prepare(args.workspace.resolve())
    if args.github_env:
        destination = os.environ.get("GITHUB_ENV")
        if not destination or any(
            "\n" in value or "\r" in value for value in values.values()
        ):
            parser.exit(1, "GitHub environment target or fixture paths are invalid\n")
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.writelines(f"{key}={value}\n" for key, value in values.items())
    print(json.dumps(values, indent=2))


if __name__ == "__main__":
    main()
