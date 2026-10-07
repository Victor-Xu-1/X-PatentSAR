# Operations and troubleshooting

## Reproducible package construction

After building/checking the frontend, use `tools/build_wheel.py --work-root
/srv/wsl/tmp --out-dir <new-output-directory>` rather than building in an old
checkout's setuptools staging tree. The shared inventory contains current Git
package inputs and exact manifest-verified UI assets. Fresh snapshots do not copy
historical `build`, egg-info, untracked source or scientific runtime data, and do
not remove those originals. The same authority audits every packaged path and
source SHA-256, refusing deleted-but-staged modules and stale bytes. Keep build
work/output and deployment receipts on E in this workstation. A successful package
audit does not establish deployment, environment cold-install or scientific QA.

## Preflight

Run `x-patentsar check-envs` and then `x-patentsar health --no-gpu --output /tmp/patentsar-health.json`. The health command performs a real DECIMER model-load probe in addition to importing the package, so it catches an interpreter that can import the module but cannot load its H5 weights. Use the GPU health path only after TensorFlow/CUDA compatibility is established.

Recognition uses the verified official printed DECIMER model only. The environment
catalog downloads printed recognition and segmentation weights, not unused
hand-drawn weights; existing operator-installed files are preserved. CPU inference
defaults to `PATENTSAR_DECIMER_CPU_THREADS=2` (1–16) and
`PATENTSAR_DECIMER_MAX_RSS_MB=4096` (2048–16384 MiB). A worker exceeding its own RSS
budget fails explicitly; the application never terminates other workloads to make
room. The sequential pipeline releases its own completed binding-phase OCR
aliases and process-local PDF/allocator caches before later model loading. It
records real RSS observations, not a promised amount of recovered host RAM.
Original OCR files/checkpoints remain intact and memory admission stays unchanged.
If headroom is still insufficient after the bounded wait, resume the task later;
the application does not lower safety budgets or stop other software to proceed.

Recognition uses a separate owned model process. Low model headroom fails before
TensorFlow load. Do not raise limits to hide
an environment fault. GPU execution must match the cache's actual execution policy.

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

The minimal default task page is `#/new-task`: PDF input and one start action only,
with no advanced-options section or hidden metadata inputs. Filename-derived title,
server-inferred patent identity and safe flags (`include_intermediates=false`,
`force=false`, empty task note) use the existing submission adapter. Upload/create and enqueue are separate
verified steps: a start failure retains the project, while uncertain responses
require a state check before retry. Notes are immutable job records, not executed
prompts. Explicit operator/API include-intermediate/force options still become actual CLI flags; safe resume
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

### Automatic six-property workbench

New Web jobs request `include_admet=true`. Extraction releases its verified owned
model process before research. Formal completion requires strict core QA. Only
a fully executed, current QA rejection may enrich individually qualified rows;
the task remains failed with `core_not_accepted`. Incomplete or technical failures
do not enter this research path.
The external pinned ADMET runtime is required for this complete Web workflow.
The CLI now uses the source-led stage order. Do not relabel an ADMET failure
as full-job success just because core artifacts were already accepted.

For existing projects, **列表选项 → 补齐结构与指标** queues the same ADMET-only job,
without rerunning PDF extraction. It first completes current source-checked
recognition for proved numbered crops lacking usable recognition, even with zero
activity observations, then computes six properties for all eligible structures.
The same small progress strip shows both phases. Missing models/transport fail
the job; rejected source chemistry remains explicit without invented SMILES or
numbers. Explicit user graph corrections/blanks are not overwritten. Online graph corrections automatically queue
only their affected compound. Coordinate/value-only edits and equivalent isomeric
graphs do not call the model. The first five RDKit properties publish separately
before model loading, with independent source/graph/runtime/algorithm evidence;
LogS failure retains these calculations, not old model numbers. Source/graph changes invalidate obsolete properties;
reset uses a new correction revision. Incomplete model outputs are never shown
as numeric placeholders. Large molecules/PROTAC predictions remain unvalidated
research observations, not an efficacy/safety or exact-graph guarantee.

Completion retains only sanitized raw model observations per original SHA in
`analysis/ocsr-observations`; old acceptance and properties are not transported.
The core converter still checks exact current image/model keys and source QC.
To recover a software-produced raw cache from another preserved workspace:

```bash
x-patentsar import-ocsr-cache --state-dir /path/to/private/web-state \
  --project-id CURRENT_PROJECT_ID --cache /path/to/raw-observations.sqlite
```

This operator-only command validates the uploaded original and bounded first-party
cache, requires the same idle analysis lease, and reports counts without loading
a model or changing compound/audit/QA data. Conflicting strings under one exact
image/model key fail rather than overwrite. Then run the normal frontend
completion action. Missing cache entries still require the configured model and
the unchanged resource guard; this is not a fallback after failed inference.

Ketcher is local Standalone 3.18.0, not an additional Linux service. Build and
package both `index.html` and `ketcher.html`, the Indigo worker and .wasm asset,
plus generated licenses. The editor is loaded only by row correction.
Do not enable JavaScript unsafe-eval or external conversion endpoints to repair
it. Check the narrowly scoped editor/worker WASM CSP and the authenticated
same-origin assets instead. Export/load failures disable saving; explicit retry
retains the last successfully parsed structure and column drafts.
Manual values remain independent overlays, including explicit blanks; they
cannot change the original prediction or formal QA. Legacy noncanonical raw
prediction digests require an exact current-string match, otherwise the result
is stale. The explicit ADMET-only action is the recovery path; do not rewrite
digests or source payloads during reads.
Corrupt saved drawing/basis addons fail reads visibly. Only the exact
authoritative original fields can be restored through an authenticated PUT
with the current source/revision proof; this is an audited revision, not
permission to edit SQLite or delete history. Ordinary different edits cannot
use that recovery boundary, and active jobs still block it.

Back up the workspace SQLite together with its private `job-history` facts and
uploaded originals. The additive `corrections`, `correction_audit` and
`admet_predictions` and rebuildable `compound_recognitions` tables remain workspace schema v1; generated core files are
unchanged. Before rollback, preserve the upgraded database, new job facts and
audited edits as a separate verified backup, then restore the pre-deployment
workspace backup together with the old wheel. Old wheels do not understand new
ADMET job specs or present correction overlays; swapping only the wheel is not
an equivalent rollback. Preserve new records for forward recovery rather than
deleting them to make an older view appear equivalent.

An unspecified document page uses `first_structure_page`; explicit deep links
and source jumps retain their chosen page after refresh. With no extracted
structure source yet, use **浏览原文** only when deliberately opening page 1.

The same recognition batch now includes confirmed numbered structures without
activities. SMILES schema v2 keeps their source observations separate from the
formal association list; both use identical chemistry/source-stereo QC and the
same six-property worker. Rejected recognized molecules cannot enter inference,
including activity-associated ones. A historical activity-only SMILES checkpoint
is not complete-catalog evidence: use the completion action for an existing
verified printed-ID catalog. If source ownership is missing, a new extraction
is needed; never assign anonymous crops guessed IDs. Product v0.1.0, API v1 and SQLite v1 remain unchanged. Software jobs establish
new source-bound records without deleting old audit; expanding source coverage alone
does not reset the independent ADMET cache/runtime identity. Do not populate
missing records by editing artifacts or reassigning ambiguous numbered crops.

The full table retains unassociated structure observations and activity-only
records. It is not a unique-compound count or proof of inactivity. Source rows
without validated SMILES after source completion are explicitly skipped by automatic metrics and retain
no numeric values; zero eligible inputs produce an empty stage, not fake success.
The complete-workflow environment preset includes both DECIMER and ADMET CPU
components; reading existing results still does not require installing models.

Locator/segmentation epochs5 retain activity-independent source coverage. Binder
epoch7 discovers numbered original cells across all selected source pages even
when no table pages were pre-labelled. Activity epoch4 follows only geometrically
proved adjacent continuations from classified seeds, preserving each cell's
actual source page. Missing/changed grids terminate continuation; no fixed patent
page lists or inferred identifier sequence are used. An eligible continuation
reuses valid OCR/segmentation checkpoints without `--force`; the changed binder
and activity epochs reject their old derived stages. Preserve the old run and
its original QA. Confirmed selected
reprints become additional sources, while unproved IDs remain numbered-pending.
Visible-label epoch8 requires matching original PDF and crop SHA-256 identities;
older or foreign label observations are not promoted. Atomic cache publication
preserves the previous file if replacement fails. A blank unused table pair is
skipped only when both original cells are empty and no segmented structure
overlaps it; drawn/unlabelled or ambiguous cells remain withheld. Repeated IDs
are allowed only in a proved selected-subset reprint of an already confirmed ID.
The raw Web corpus layout changes to compound-catalog-v1; a projection rebuild stales old
source-bound overlays/predictions but preserves their audit. Review before
explicitly reapplying an edit. Rollback must restore the pre-deployment database
together with its wheel, retaining newer state separately for forward recovery.

Per-column menus provide project-wide filter/sort with searchable value checklists,
select-all/blank and explicit OK/Cancel drafts. Choice search only narrows the menu;
it never automatically unchecks unseen rows. Inclusive/exclusive selection supports
all-minus-exceptions without serializing every project value. Each selection has
at most 200 exceptions/explicit values, under the existing 16 KiB query budget;
excess fails visibly, not by dropping choices. Conditions and color selection
replace the same column's checklist; other columns remain in conjunction.
Only an opened menu loads choices, obeying other column/global filters but ignoring
its own applied filter. At most 200 distinct values per choice page; use search and
choice-page controls for larger lists. The full vocabulary is capped at 25,000
distinct values/four million characters; overflow is explicit. No PDF/model work
is performed for this query. Color filter/sort uses the same full-project bands,
not a new ranking after filtering. Missing/unknown values are in the uncolored band.
Toolbar **列** restores hidden
columns, including all-hidden recovery. Query parameters survive refresh. TSV
copy is limited to current-page selected/all rows and visible fields; use the
normal CSV/JSON export for all filtered rows. Numeric filters never force censored
measurements into scalars, and stored-property filtering never starts a model.
The activity-band legend is on demand in display options; bands use the complete
effective project and preserve ties, not current-page extrema.

Open the direct topbar **环境管理** entry (`#/settings`). Upload, recent files,
environment management, job history and actual product version stay visible;
workspace result/evidence shortcuts also stay visible. Small screens wrap controls
without hiding captions; there is no Header More menu. Use **一键部署全部环境** for the default
PDF/structure/activity/six-property workflow, not manual component assembly. One
complete CPU/download/license confirmation creates one durable operation. It
rechecks/reuses qualified components, provisions deficient ones in owned prefixes
and activates only after all six are verified. ADMET runtime/models are included.
Existing ready components are not blindly reinstalled; probe timeouts/resource
errors fail visibly rather than becoming a reason to duplicate environments.
All-ready status offers full inspection instead of repeated deployment. The
default page contains overall readiness, complete setup and active progress/cancel
only. Location editing and actual component checks use one separate details entry;
logs/history/internal IDs remain server-side operator evidence, not everyday UI.
The application/WSL Linux x86_64 Python 3.12 Web startup prerequisite remains a
bootstrap boundary; this page does not install WSL, system packages or GPU drivers.
The approved Linux root is configured by `PATENTSAR_ENVIRONMENT_ALLOWED_ROOT`; the
default new prefix is `PATENTSAR_ENVIRONMENT_ROOT`. Native Linux x86_64 Python 3.12
is required for this controller. On the E-drive workstation these paths are
`/srv/wsl/envs` and `/srv/wsl/envs/x-patentsar-managed`, inside `E:\WSL\system`.

The catalog is cheap metadata; actual inspection may take tens of seconds for
TensorFlow/PyTorch loads. Downloads run as durable owned jobs, limited to two hours
by default. Logs, hashed download cache, operation plans and environment SQLite
live in private `web-state/environments`. There is one active operation at a time;
repeated request IDs reuse the saved result rather than replay downloads blindly.

The catalog always shows configured component locations and lightweight presence.
An existing path is **not** a verified environment. Current successful checks show
installed/verified; existing unchecked or stale paths ask for inspection, not a
duplicate install. Failed/incompatible probes remain failures even when files exist.
Measured and target versions are separate. Same-path previous checks remain
historical after a recipe/config change; a new path never inherits those checks.
Per-component times refer to actual publication for that component; legacy times
may be unknown. Refresh only rereads metadata. Use full inspection or an advanced
component inspection for a fresh module/model check, without downloads.
`environment_inspection_changed` means the configuration/recipe snapshot changed
during a check. Its operation files/history are retained, no configuration is
changed and no report is promoted. Refresh and explicitly inspect again after
the operator change has settled. No database edits or file relocation are needed.

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

- `stereo_source_conflict` / `stereo_source_ambiguous`: a source unknown-bond risk and the model's determinate stereo cannot be safely reconciled. Inspect the original crop; do not strip chiral tokens, flip R/S by suffix, merge separated IDs, or run normalization repeatedly. Generated observations and old failed runs remain unchanged. Correct supported chemistry through the audited drawing overlay; it does not turn a failed core run into accepted formal chemistry.
- `stereo_source_unavailable`: unreadable/excessive source geometry failed the bounded screen before model loading. Correct input quality or source ownership, not memory limits or acceptance flags.
- Unknown single/crossed-double manual MDL stays lossless in save/redraw/export. Explicit unresolved manual stereo cannot acquire a determinate model result from a previous graph. OR/AND and special stereo remain visibly unsupported. Plain-SMILES legacy research results are not proof of source stereo fidelity.

New tasks use source-led pipeline 3.0.0 and ruleset 2.1.0 while the product remains v0.1.0. Existing original
PDFs, model observations, QA and manual audits are retained; a new task uses current
validation instead of relabelling historical results. Only original-SHA-verified
raw OCR/model observations may be reused. Missing old stereo evidence stays unknown.
For raw OCR, supported activity-led2.0.0 and source-led3.0.0 producer envelopes
can share observation-format1 after exact original SHA, size and page-count
verification. Derived classifications, structures, chemistry and QA still require
their own current identities; this is not a legacy acceptance exception.

- `LLM_API_KEY is not set`: deterministic production stages still run normally; optional advisory QA is recorded as `skipped_no_credentials`. Configure a key only when advisory review is wanted.
- DECIMER unavailable: verify `DECIMER_PYTHON` points to a Python 3.10 environment, import `decimer_segmentation` in that interpreter, and run health again. Do not force TensorFlow 2.15 into the Python 3.12 orchestrator.
- PaddleX endpoint unavailable: verify `PATENTSAR_PADDLEX_OCR_URL`; the pipeline must report the degraded OCR path rather than silently claiming equivalent evidence.
- Strict acceptance failure: inspect `final_qa_report.json` and `STRICT_ACCEPTANCE_FAILED.json`. Do not manually edit generated tables to bypass the gate.
- Reused stale data: current caches require an exact namespaced schema and content fingerprint. Rerun with `--force` to deliberately invalidate current stage outputs.
- Repeated printed source number: preserve spatially separate occurrences and inspect original cell/heading evidence. Activity membership, a missing number in a sequence or a similar structure cannot renumber a crop. Ambiguous/conflicting ownership remains unresolved and fails strict coverage; do not manually renumber generated outputs.
- Long scanned-page text without coordinates: older RapidOCR generation omitted coordinates above a native-text threshold. The current observation path stores text and coordinates from one inference. Reuse requires validated original SHA, compatible raw cache identity and usable required geometry; otherwise rerun the observation stage. Never fill coordinates manually; native-text pages legitimately have no OCR coordinates.

## Concurrency and recovery

During structure segmentation, the slim workflow reports saved pages/selected
pages, not a time-estimated percentage or accepted molecule count. Reused
validated chunks contribute their pages immediately; newly completed chunks
contribute only after fresh metadata and checkpoint validation. Completed
windows publish the observations. Unknown device/RSS is not fabricated.
This progress does not publish incomplete chemistry or bypass the existing
completed-stage projection/strict-QA boundary.
Checkpoint transport obtains its stage order from the same core registry. A
source-first task can preserve validated locator and completed segmentation
chunks before activity extraction starts. No missing downstream artifact may
prematurely stop copying an earlier declared stage; invalid dependencies still
reject reuse. Final outputs, acceptance and old history are never transported.
Each segmentation job receives a bounded input-fingerprint file. The worker
recomputes it against the original PDF and declared locator/crop dependencies,
then seals each fresh successful chunk immediately with the existing manifest
writer. A later interrupted chunk cannot erase earlier sealed work. Inputs are
rechecked after inference; changed dependencies never acquire a checkpoint.
The parent validates worker-sealed manifests rather than creating a second
checkpoint writer. Old metadata without a manifest stays unproved and retained.

PDFs without a readable patent identifier retain the task's explicit unknown value through CLI execution and resume; the upload's temporary filename is never promoted to a patent identifier. Standalone CLI omission still permits the existing filename inference. Explicit `--patent-id ""` requires an explicit output directory.

Use **继续提取** after restarting the application. Startup reconciles active
records and interrupted records whose prior cleanup was unverified. A valid
different Linux kernel boot proves old processes cannot survive: no current PID
or process group is signalled on that proof. Same-boot cleanup requires exact
owned identity. Canonical workspace/job, command, executable, phase, PID/start
time and bounded descendant proofs remain mandatory. Malformed, foreign or
unreadable evidence stays blocked, not guessed or deleted.

Verified recovery saves original identity in private `web-state/job-recovery`
before publishing resumability. Existing job-history and run files are not
rewritten. Do not edit boot/identity fields or delete proof to bypass protection.
Product remains v0.1.0; API and workspace SQLite remain v1.

Checkpoint preparation is one durable queued attempt. Copying and projection
serialization no longer hold SQLite's writer. The worker cannot claim unready
attempts; cancellation remains authoritative. Interrupted preparations retain
their declared inactive source for the next safe resume. Source ancestry cannot
cross projects or inherit an owned producer. Compatible completed segmentation
batches are preserved even if the overall stage was interrupted; unfinished or
incompatible batches run normally under current fingerprints. OCR/raw recognition
and strict QA gates remain unchanged.

The compact strip shows actual interrupted/failed core work, not an unstarted
ADMET failure marker. The declared post-core ADMET/property step stays visible as
waiting/unexecuted, without fabricated counts, while core work is incomplete.
Actual ADMET, including prediction-only jobs, remains visible; source completion
and six-property progress retain their actual separate workloads. A missing final
research record is unknown, not inferred complete from core QA alone.
Resume preserves saved parameters, disables force and never blindly replays an
uncertain write before reloading current task state.

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
An ordinary non-force rerun uses the same bounded transport when the current
original observations and latest stopped job's private output can be verified.
New task options remain new; no old history, failure marker or final acceptance is
copied. Compatible older OCR remains a raw input rather than a derived checkpoint.
Resume uses the core PDF-SHA/observation predicate for this raw OCR boundary, not
the newer derived-artifact ruleset; unknown observation contracts still fail.
Web resume now creates a new job-ID directory and copies only verified bounded
checkpoints; it never aliases the old output directory or hardlinks images. The CLI
remains the final cache/acceptance authority. Old jobs sharing an output root show
history unavailable, not a fabricated stage snapshot. Terminal new-job history is
write-once under private `job-history/`; preserve it together with workspace state.
Binding fingerprints also include the implementation epoch from `contracts.py`;
changing catalog/caption ownership rebuilds binding without discarding unchanged
segmentation. Complete confirmed spatial coverage skips generic repair. Do not
edit failed binding files, OCR labels or final QA to make a checkpoint reusable.

The raw OCSR epoch also participates in stage fingerprints and exact-image cache
keys. Old corrected model strings cannot seed it.
Resume transports a bounded, sanitized snapshot of successful current-epoch raw
observations only after the bindings checkpoint is independently verified. Exact
payloads, image hashes, model fingerprints and timestamps stay unchanged. Foreign
SQLite schema/triggers, repaired legacy entries, failures and final QA are not
copied. The sole converter rechecks image/runtime identity and current RDKit QC;
failed or changed inputs execute normally, without promoting cached acceptance.
The production worker explicitly
enables one normalization retry on the same source image; standalone workers retain
no retry unless `--retry-normalization` is set. This is independent of initial
`--preprocess`/`--no-preprocess`. Inspect `engine_attempts` for every original raw
prediction and input image hash. Do not manually replace wildcards, element letters,
ring numbers or chiral tags to bypass a failure.

The extraction-repair verification scope follows the affected chain: cell ownership
and suffix/ambiguity unit regressions; real original-PDF binding and raw DECIMER
inference; SQLite/API live-checkpoint and failure states; frontend run-switch,
crop/source navigation and installed-wheel browser checks. Pass criteria are complete
proved printed-ID structure coverage, unique existing images, per-metric provenance, strict SMILES QC,
and final deterministic acceptance. Optional research/ADMET analysis is not an
alternative acceptance path and is outside this repair's scientific validation.

For missing crop messages, distinguish unexecuted/unfinished segmentation,
unmatched structures, unavailable generated assets and browser load errors.
The original PDF can remain available during a failed extraction. A current failed
or incomplete run is not classified as a historical import simply because its
downstream artifacts do not yet exist. Each activity metric's source page may differ
from the bound structure page.
After a software/rules update, the first project/result access rebuilds an outdated
SQLite projection once from the retained source artifacts. Old-rule acceptance is
then historical, not current. This changes only rebuildable presentation data;
original artifacts and manual-review decisions are retained.

Structure details distinguish original crops from RDKit SMILES redraws. Compare
both for recognition errors; a syntactically valid SMILES does not prove atom,
bond or stereochemistry fidelity to the patent. Token probabilities are explicitly
uncalibrated. Actual progress/cache/device/RSS counters are observations, not final
acceptance. Use density/metric-column controls for large result tables; hiding a
column does not drop its underlying measurement or change export content.

The architecture-optimization validation scope includes stage-cache invalidation,
recognized-but-withheld source ownership, immutable attempt history/checkpoint
transport, bounded model protocol and memory, additive DTOs and manual counts,
real original-PDF inference, installed-wheel/browser source/redraw navigation and
table density. Exact-model raw-string regression and controlled graph/stereo
oracles answer different questions; neither alone proves all-patent accuracy.

The current official printed recognizer has a known exact-graph failure on the
controlled 700×500 ethanol depiction in `tests/test_ocsr_gold.py`: it returns an
extra carbon despite valid RDKit syntax. Simple scaling/normalization is not a
verified fix; another official weight set instead miscounts a ring on this corpus.
Do not switch weights, splice model outputs, repair strings or advertise chemical
accuracy from syntax/token probabilities. Keep the explicit real-model oracle
failure separate from passing engineering/strict-export gates until a model or
independent original-graph verification improvement actually resolves it.

Use a separate output directory per patent and avoid running two processes against the same output directory. A stopped run can normally be resumed without `--force`; matching stage fingerprints are reused. Use `--force` only when the underlying PDF, rules or intended parameters changed materially.

Large scanned patents can spend several minutes in the first full-page OCR pass. The page cache is atomically checkpointed every ten completed pages, so after an interruption rerun without `--force` to resume it. A 146-page image-only WIPO sample exceeded a 10-minute verification window on this workstation; a three-page structure-table subset completed in 25 seconds, and its cached rerun completed in under one second. Treat first-pass OCR throughput as workload-dependent rather than a fixed service-level guarantee.

Activity extraction runs in an isolated subprocess with a bounded workload-aware timeout: 30 minutes minimum, 10 seconds per classified activity page, and 3 hours maximum. This prevents small jobs from hanging indefinitely while allowing large scanned patents to complete. A timeout remains a hard failure and must not be converted into partial acceptance.

## Logs and retention

Retain the final workbook, SDF, `pipeline_summary.json`, `final_qa_report.*`, optional `llm_qa_report.*`, and any failure marker as one audit unit. Remove OCR caches and intermediate images according to local data-retention policy only after the final audit unit is archived.

## Rollback

### Mainline deployment gate

A task is not complete at branch push or PR creation. Review and merge every
task-related PR into `main`, fetch the exact remote merge revision, and build the
frontend/wheel from that clean source. Do not replace unrelated dirty work or
merge unknown PRs merely to empty the queue. Keep product version `v0.1.0` unless
the user explicitly requests a version change.

Select verification from the exact integrated diff and its affected consumers;
global suites require explicit user authorization. Do not disable required CI
checks or branch protection. If an authorized focused run cannot satisfy a
required gate, report the conflict instead of claiming success. Skipped CI is not
passing CI, and a known scientific limitation is not resolved by a Git merge.

Before replacing the installed wheel, confirm this application's extraction,
environment-install and research-analysis operations are idle. Preserve the
previous wheel, its checksum, and the current external configuration. Stop only
the verified owned service, install the mainline wheel without changing unrelated
environments, and restart through the existing operator entry point. Never
restart all WSL distributions or migrate user state as a deployment shortcut.

Record the PR/merge SHA, clean source tree, wheel and served asset checksums,
installed product version, focused test commands/results, startup/health and real
browser evidence in the external E-drive evidence store. Confirm there are no
remaining task-related open PRs. The Windows management entry must reference this
current deployment, not an older branch or historical CI run. Rollback reinstalls
the preserved wheel through the same idle/ownership checks; patent artifacts and
manual-review records are never edited or deleted.

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
