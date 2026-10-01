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

The complete task page is `#/new-task`. Upload/create and enqueue are separate
verified steps: a start failure retains the project, while uncertain responses
require a state check before retry. Notes are immutable job records, not executed
prompts. Include-intermediate/force options become actual CLI flags; safe resume
preserves original notes/options but disables force checkpoint invalidation.

Local analysis uses `PATENTSAR_ADMET_PYTHON`, `PATENTSAR_ADMET_MODEL_DIR`, the
existing DECIMER interpreter and `PYSTOW_HOME`. Follow the pinned CPU installation
and SHA-verified model preparation commands in README; never replace unknown
model files or move Linux environments between incompatible prefixes. No Java
PaDEL task, DrugBank comparison or remote molecule submission is performed.

Analysis runs one CPU request at a time with a 180-second lifetime, bounded JSON
and resident memory. Concurrent work receives `analysis_busy`; client disconnect,
timeout and shutdown stop only verified owned children. A shutdown that cannot
verify child termination fails closed and retains workspace ownership while
still attempting extraction queue cleanup. Do not bypass that lock to recover.
Research caches are private rebuildable state in `web-state/analysis`, not a
second extraction/acceptance authority.

This workstation's original WO2026156070 PDF has been recovered to E and attached
after its SHA-256 matches the historical source exactly. All 1,553 original pages
are available; old OCR remains marked historical and is not described as the
original page image. The historic core artifacts still do not constitute current
formal QA. Original recovery is not permission to rewrite generated artifacts.

Uploaded PDFs, new run outputs, private job logs and workspace.sqlite3 live under
the Web state root. Preserve that root as a unit after stopping PatentSAR jobs.
Do not copy a live SQLite/WAL database as a verified cold backup. Restart recovery
marks interrupted jobs explicitly; resume only through the application's job
controls. A second server must not share an active workspace.

## Managed environment operation

Open **环境管理** (`#/settings`) and inspect components before installing. The
approved Linux root is configured by `PATENTSAR_ENVIRONMENT_ALLOWED_ROOT`; the
default new prefix is `PATENTSAR_ENVIRONMENT_ROOT`. Native Linux x86_64 Python 3.12
is required for this controller. On the E-drive workstation these paths are
`/srv/wsl/envs` and `/srv/wsl/envs/x-patentsar-managed`, inside `E:\WSL\system`.

The catalog is cheap metadata; actual inspection may take tens of seconds for
TensorFlow/PyTorch loads. Downloads run as durable owned jobs, limited to two hours
by default. Logs, hashed download cache, operation plans and environment SQLite
live in private `web-state/environments`. There is one active operation at a time;
repeated request IDs reuse the saved result rather than replay downloads blindly.

Only reviewed fixed packages and official model files are accepted. No `sudo`,
system package changes, global uv/Python replacement, GPU setup or remote molecule
submission occurs. All new prefixes include operation identity; existing valid
environments may be reused. Never copy a Python environment to a different prefix.

An install publishes interpreter/model paths atomically to the existing external
`env_paths.local.yaml` only after actual verification. The old configuration is
saved under its private `.environment-backups` directory. Startup wrappers should
not supply implicit `PYSTOW_HOME`/ADMET/installer overrides: persist operator
defaults in that YAML instead. Intentional explicit variables still take priority;
the installer reports a conflict instead of pretending they changed.

For network/TLS/hash/disk/permission failures, correct the reported cause and
explicitly retry. TLS/hash checks are never disabled. Unknown directories,
symlinks or modified cached content are preserved and refused. An existing
prefix must be private (0700); its permissions are not changed by the manager.
On cancellation/restart only verified owned processes are stopped; incomplete
prefixes are not activated or automatically deleted. Re-inspect before retrying.
Do not bypass an ownership/cleanup error with global WSL shutdown.

If verification succeeds but activation reports `analysis_busy` or a configuration
revision conflict, finish the active analysis, re-inspect and install/reuse again.
Running extraction jobs keep their startup configuration snapshot. Location changes
apply only to future installations and are not migrations or cleanup requests.

## Common failures

- `LLM_API_KEY is not set`: deterministic production stages still run normally; optional advisory QA is recorded as `skipped_no_credentials`. Configure a key only when advisory review is wanted.
- DECIMER unavailable: verify `DECIMER_PYTHON` points to a Python 3.10 environment, import `decimer_segmentation` in that interpreter, and run health again. Do not force TensorFlow 2.15 into the Python 3.12 orchestrator.
- PaddleX endpoint unavailable: verify `PATENTSAR_PADDLEX_OCR_URL`; the pipeline must report the degraded OCR path rather than silently claiming equivalent evidence.
- Strict acceptance failure: inspect `final_qa_report.json` and `STRICT_ACCEPTANCE_FAILED.json`. Do not manually edit generated tables to bypass the gate.
- Reused stale data: current caches require an exact namespaced schema and content fingerprint. Rerun with `--force` to deliberately invalidate current stage outputs.
- Repeated I-series source number: ruleset 2.0.1 preserves spatially separate occurrences and only corrects a unique, activity-supported gap. Inspect `authoritative_table_source_label` and the correction reason. Ambiguous or unsegmented competing occurrences fail closed; do not manually renumber outputs.
- Long scanned-page text without coordinates: older RapidOCR cache generation omitted coordinates when text exceeded the native-text threshold. Ruleset 2.0.1 stores both from one inference and rejects previous manifest identities. Rerun rather than manually filling coordinate entries; native-text pages legitimately have no OCR coordinates.

## Concurrency and recovery

After an accuracy-ruleset change, use **运行提取** to establish a new run. A job
from a different runtime identity is not relabelled or resumed. The queue retains
the old run and automatically reuses supported, exact-original-SHA OCR observations
from that same private project. All derived stages run with the current rules.
For standalone use, `run --reuse-ocr-cache /path/to/page_ocr_cache.json` provides
the same checked input boundary; it cannot be combined with `--force` and never
overwrites an existing target cache. Unknown/incorrect observation contracts are
refused. Do not edit old metadata or generated activity/binding/QA to force reuse.

Current CPU OCR uses two intra-operation threads and one inter-operation thread
per engine; the configured engine is shared by page, table and cell consumers.
DECIMER remains isolated and CPU-stable where the TensorFlow/GPU pair is unsupported.
Model/resource limits and actual stage counts are not evidence of chemical QA:
inspect final deterministic acceptance after the full run completes.

Within the current runtime identity, resume keeps compatible upstream checkpoints.
Binding fingerprints also include the implementation epoch from `contracts.py`;
changing catalog/caption ownership rebuilds binding without discarding unchanged
segmentation. Complete confirmed spatial coverage skips generic repair. Do not
edit failed binding files, OCR labels or final QA to make a checkpoint reusable.

The raw OCSR epoch also participates in stage fingerprints and exact-image cache
keys. Old corrected model strings cannot seed it. The production worker explicitly
enables one normalization retry on the same source image; standalone workers retain
no retry unless `--retry-normalization` is set. This is independent of initial
`--preprocess`/`--no-preprocess`. Inspect `engine_attempts` for every original raw
prediction and input image hash. Do not manually replace wildcards, element letters,
ring numbers or chiral tags to bypass a failure.

The extraction-repair verification scope follows the affected chain: cell ownership
and suffix/ambiguity unit regressions; real original-PDF binding and raw DECIMER
inference; SQLite/API live-checkpoint and failure states; frontend run-switch,
crop/source navigation and installed-wheel browser checks. Pass criteria are exact
active-ID order, unique existing images, per-metric provenance, strict SMILES QC,
and final deterministic acceptance. Optional research/ADMET analysis is not an
alternative acceptance path and is outside this repair's scientific validation.

For missing crop messages, distinguish unexecuted/unfinished segmentation,
unmatched structures, unavailable generated assets and browser load errors.
The original PDF can remain available during a failed extraction. A current failed
or incomplete run is not classified as a historical import simply because its
downstream artifacts do not yet exist. Each activity metric's source page may differ
from the bound structure page.

Use a separate output directory per patent and avoid running two processes against the same output directory. A stopped run can normally be resumed without `--force`; matching stage fingerprints are reused. Use `--force` only when the underlying PDF, rules or intended parameters changed materially.

Large scanned patents can spend several minutes in the first full-page OCR pass. The page cache is atomically checkpointed every ten completed pages, so after an interruption rerun without `--force` to resume it. A 146-page image-only WIPO sample exceeded a 10-minute verification window on this workstation; a three-page structure-table subset completed in 25 seconds, and its cached rerun completed in under one second. Treat first-pass OCR throughput as workload-dependent rather than a fixed service-level guarantee.

Activity extraction runs in an isolated subprocess with a bounded workload-aware timeout: 30 minutes minimum, 10 seconds per classified activity page, and 3 hours maximum. This prevents small jobs from hanging indefinitely while allowing large scanned patents to complete. A timeout remains a hard failure and must not be converted into partial acceptance.

## Logs and retention

Retain the final workbook, SDF, `pipeline_summary.json`, `final_qa_report.*`, optional `llm_qa_report.*`, and any failure marker as one audit unit. Remove OCR caches and intermediate images according to local data-retention policy only after the final audit unit is archived.

## Rollback

Before an environment-manager rollback, finish/cancel its active operation and
verify owned-child shutdown. Preserve the whole private environment state and the
current external configuration. If restoring configuration, select the saved
operation-specific YAML backup deliberately; no generated patent files or other
software environments need modification. Old application builds do not own or
resume this new environment database. Keep immutable installed prefixes for
operator review; rollback is not permission to delete them.

Before a workbench rollback, finish or explicitly cancel jobs created by the new
task interface. Older code can view retained historical artifacts but cannot be
assumed to resume specifications containing new task parameters. Preserve the
private workspace and analysis cache separately; do not strip fields from jobs
or alter output files to make an older binary accept them.

The restored source is `/srv/wsl/projects/patent-sar-extractor`; the external source archive and pre-optimization snapshot are preserved on E. Stop only PatentSAR jobs before restoring that snapshot or switching its entry point. The historical plugin path is not a verified active deployment in this recovered environment. Outputs are not schema-migrated in place; preserve each run directory before changing versions. Never shut down all WSL distributions merely to roll back this application.
