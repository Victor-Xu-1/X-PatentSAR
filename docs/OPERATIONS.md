# Operations and troubleshooting

## Preflight

Run `x-patentsar check-envs` and then `x-patentsar health --no-gpu --output /tmp/patentsar-health.json`. The health command performs a real DECIMER model-load probe in addition to importing the package, so it catches an interpreter that can import the module but cannot load its H5 weights. Use the GPU health path only after TensorFlow/CUDA compatibility is established.

The recovered E-drive deployment has an operator-owned entry point at `/srv/wsl/envs/patentsar/bin/x-patentsar` (Windows: `E:\WSL\apps\x-patentsar\X-PatentSAR.cmd`). It loads external interpreter configuration and selects E-drive state/cache/model paths, with CPU inference by default. `PYSTOW_HOME=/srv/wsl/models/patentsar` points DECIMER OCSR to the restored weights. Segmentation health is not proof that OCSR inference succeeds; verify a real crop separately. Do not change `HOME` to find old model weights.

## Web operation

Run `x-patentsar serve --port 8765` with a built frontend or installed Web wheel.
The local E-drive deployment uses port 18765 because the portable default is
occupied by existing applications. `--api-only` is explicit frontend-development
mode; production startup requires the built UI. Bind hosts are limited to
loopback and Uvicorn uses one worker. The service enforces same-origin sessions,
CSRF, upload limits and private operator-owned SQLite state.

Use `x-patentsar import-run --run-dir ...` to attach existing results read-only.
Historical imports preserve the original generated files. Reviews have separate
revisioned records and cannot promote formal acceptance. Web exports include the
acceptance state; review-only output is not a formal chemistry deliverable.

Uploaded PDFs, new run outputs, private job logs and workspace.sqlite3 live under
the Web state root. Preserve that root as a unit after stopping PatentSAR jobs.
Do not copy a live SQLite/WAL database as a verified cold backup. Restart recovery
marks interrupted jobs explicitly; resume only through the application's job
controls. A second server must not share an active workspace.

## Common failures

- `LLM_API_KEY is not set`: deterministic production stages still run normally; optional advisory QA is recorded as `skipped_no_credentials`. Configure a key only when advisory review is wanted.
- DECIMER unavailable: verify `DECIMER_PYTHON` points to a Python 3.10 environment, import `decimer_segmentation` in that interpreter, and run health again. Do not force TensorFlow 2.15 into the Python 3.12 orchestrator.
- PaddleX endpoint unavailable: verify `PATENTSAR_PADDLEX_OCR_URL`; the pipeline must report the degraded OCR path rather than silently claiming equivalent evidence.
- Strict acceptance failure: inspect `final_qa_report.json` and `STRICT_ACCEPTANCE_FAILED.json`. Do not manually edit generated tables to bypass the gate.
- Reused stale data: current caches require an exact namespaced schema and content fingerprint. Rerun with `--force` to deliberately invalidate current stage outputs.
- Repeated I-series source number: ruleset 2.0.1 preserves spatially separate occurrences and only corrects a unique, activity-supported gap. Inspect `authoritative_table_source_label` and the correction reason. Ambiguous or unsegmented competing occurrences fail closed; do not manually renumber outputs.
- Long scanned-page text without coordinates: older RapidOCR cache generation omitted coordinates when text exceeded the native-text threshold. Ruleset 2.0.1 stores both from one inference and rejects previous manifest identities. Rerun rather than manually filling coordinate entries; native-text pages legitimately have no OCR coordinates.

## Concurrency and recovery

Use a separate output directory per patent and avoid running two processes against the same output directory. A stopped run can normally be resumed without `--force`; matching stage fingerprints are reused. Use `--force` only when the underlying PDF, rules or intended parameters changed materially.

Large scanned patents can spend several minutes in the first full-page OCR pass. The page cache is atomically checkpointed every ten completed pages, so after an interruption rerun without `--force` to resume it. A 146-page image-only WIPO sample exceeded a 10-minute verification window on this workstation; a three-page structure-table subset completed in 25 seconds, and its cached rerun completed in under one second. Treat first-pass OCR throughput as workload-dependent rather than a fixed service-level guarantee.

Activity extraction runs in an isolated subprocess with a bounded workload-aware timeout: 30 minutes minimum, 10 seconds per classified activity page, and 3 hours maximum. This prevents small jobs from hanging indefinitely while allowing large scanned patents to complete. A timeout remains a hard failure and must not be converted into partial acceptance.

## Logs and retention

Retain the final workbook, SDF, `pipeline_summary.json`, `final_qa_report.*`, optional `llm_qa_report.*`, and any failure marker as one audit unit. Remove OCR caches and intermediate images according to local data-retention policy only after the final audit unit is archived.

## Rollback

The restored source is `/srv/wsl/projects/patent-sar-extractor`; the external source archive and pre-optimization snapshot are preserved on E. Stop only PatentSAR jobs before restoring that snapshot or switching its entry point. The historical plugin path is not a verified active deployment in this recovered environment. Outputs are not schema-migrated in place; preserve each run directory before changing versions. Never shut down all WSL distributions merely to roll back this application.
