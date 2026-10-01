# Architecture

## Product boundary

X-PatentSAR is a standalone Linux/WSL application. Its command-line boundary is `x-patentsar` plus documented filesystem inputs, configuration and outputs. It has no runtime dependency on Synon processes, APIs, plugin registries or user workspaces. The new Web presentation layer uses the same application/CLI pipeline; it does not add another extraction engine.

Only `x-patentsar run` produces a formal activity-led result. Commands labelled as diagnostic may inspect or generate intermediate material, but their outputs cannot satisfy formal binding, SMILES or QA gates. Manual Web reviews are separately persisted annotations and cannot change generated extraction artifacts or acceptance.

## Layer ownership

```mermaid
flowchart TB
    CLI["cli.py<br/>argument parsing and dispatch"] --> APP["application/<br/>use cases, stage policy, cache and acceptance orchestration"]
    APP --> CORE["core/<br/>deterministic extraction, binding, OCSR QC and formal QA"]
    APP --> INT["integrations/<br/>optional external LLM/VLM adapters"]
    APP --> WORKERS["workers/<br/>isolated-process entry points"]
    WORKERS --> CORE
    CORE --> SHARED["contracts.py + artifact_io.py + failures.py"]
    INT --> SHARED
```

Dependency direction is enforced by tests: `core/` does not import `application/`, `integrations/`, or the removed `orchestration/` package. External model configuration and HTTP calls live under `integrations/`; the CLI contains presentation logic only.

```text
src/patent_sar_extractor/
  cli.py                   command-line presentation
  application/             typed stage registry, use cases and acceptance policies
    pipeline.py             sole ordered extraction coordinator
    pipeline_context.py     explicit data exchanged by the eight stage handlers
    stage_*.py              one handler per stage; stage_cache owns fingerprints
  core/                    deterministic domain and extraction engines
    series_table_binding.py typed I-series geometry/evidence resolution
    structure_binder.py     source-ownership coordinator and one artifact writer
    binding_*.py            geometry, observations, candidates and strict arbitration
    ocsr/                   DECIMER-only recognition, cache and RDKit QC
  integrations/llm/        optional LLM advisory QA and VLM adapter
  workers/                 isolated Python-process entry points
  defaults/                immutable packaged configuration
  contracts.py             product, pipeline, ruleset and schema authority
  artifact_io.py           atomic JSON read/write boundary
  failures.py              single strict-failure marker authority
  smiles_artifact.py       canonical SMILES artifact envelope
```

## Web presentation and state

```mermaid
flowchart LR
    UI["React workbench<br/>PDF, activity, review, tasks"] --> API["Loopback API<br/>session, CSRF, validated DTOs"]
    API --> DB["Private SQLite<br/>projects, jobs, reviews"]
    API --> READ["Read-only artifact view<br/>original PDF and generated results"]
    API --> JOB["Owned bounded job runner"]
    JOB --> CLI["Existing x-patentsar run"]
    CLI --> CORE["Activity-led extraction and deterministic QA"]
    CORE --> READ
```

The UI never reads local paths directly or runs extraction code. The API validates
uploaded originals, renders bounded pages and reads canonical artifact identity
envelopes. Jobs invoke the existing CLI in one owned process group. SQLite review
annotations are separate from extraction artifacts; there is no manual path to
change binding/SMILES/QA files or declare a failed run formally accepted.

`frontend/dist` is build output. The controller-owned packaging tool verifies and
copies it into the wheel's private package static directory. The installed wheel
serves both UI and API from one origin; Node.js is a build dependency only.

Results use compact/comfortable density and independently selected metric columns.
Each measurement retains its assay, unit and original source navigation, including
multiple measurements of the same metric. The six statistics share one compact
strip: binding evidence and actual SQLite manual decisions are distinct counters.
Original crops and bounded RDKit PNGs appear side by side; a redraw is explicitly
not original evidence. Token probabilities are uncalibrated observations, never
chemical-accuracy percentages or manual approvals.

### Task and analysis boundaries

The task page first uploads and validates an original, then explicitly creates a
durable extraction job. A failed start retains the uploaded project and exposes
recovery; uncertain writes are not blindly replayed. Operator notes are records,
not executable prompts. Intermediate/force options become real CLI flags, while
safe resume retains checkpoints and never repeats force invalidation.

Each new attempt, including resume, receives an independent job-ID output root.
Resume copies only bounded, content-verified upstream checkpoints, relocates
declared image/path fields and preserves raw chemistry/provenance exactly. The
CLI rechecks current fingerprints and strict acceptance; transport is not a second
cache authority. Terminal attempts seal private write-once stage snapshots.
An ordinary rerun also uses this same transport when the latest stopped job's
current-runtime private output and exact PDF observations are verified. It retains
the new request's options and never inherits old history or acceptance. Changed
rules/runtime retain only independently compatible raw OCR; `force` starts fresh.
Legacy jobs sharing a mutable output root report `history_available=false` rather
than inheriting a later run's successful stages. No SQLite migration or in-place
rewrite of old generated artifacts is required.

`smiles/progress.json` atomically publishes actual completed/total, cache hits,
failures, execution device and measured peak RSS. The existing job read path
validates its version and bounded counters; no extra poller, predicted ETA or
guessed success percentage is introduced. Reused checkpoint facts are recorded
explicitly, and cached observations do not pretend to measure current resources.

`web/result_queries.py` owns filtering, reviews, pagination and presentation
coordinates. It validates the original SHA and bounds across filtered rows but
loads PDF pages only for visible-row coordinate transforms. The service remains
the workspace use-case boundary; query logic has no competing implementation.

The molecular analysis integration is a separate research-only consumer of the
same original/crops and validated molecules. DECIMER recognition, RDKit QC and
ADMET-AI CPU model predictions do not rewrite generated pipeline artifacts or
promote formal acceptance. Its rebuildable private cache is independent from
authoritative project/job/review state. Evidence summaries aggregate source
fields and preserve units/censored values; they do not invent model-generated
mechanism or efficacy claims.

```mermaid
flowchart LR
    TASK["Task input / original PDF"] --> QUEUE["Existing durable CLI queue"]
    QUEUE --> QA["Deterministic formal QA"]
    ORIGINAL["Verified original / real crops"] --> VIEW["PDF and result presentation"]
    ORIGINAL --> OCSR["Research DECIMER + RDKit QC"]
    OCSR --> ADMET["Isolated ADMET-AI CPU inference"]
    ADMET --> CACHE["Research-only analysis cache"]
    VIEW --> SUMMARY["Source-grounded evidence statistics"]
```

## Local environment control

```mermaid
flowchart LR
    ENVUI["Environment manager<br/>location, presets, consent, history"] --> ENVAPI["Existing session/CSRF API"]
    ENVAPI --> ENVDB["Private environment SQLite v1<br/>revision and idempotent plan"]
    ENVDB --> OWNED["Same owned subprocess carrier<br/>persisted identity + handshake"]
    OWNED --> FIXED["Fixed CPU recipes<br/>hash-locked wheels and models"]
    FIXED --> CHECK["Actual PDF/OCR/module/model probes"]
    CHECK --> CONF["Atomic external env_paths.local.yaml<br/>config conflict + analysis-use gate"]
    CONF --> NEXT["New CLI/analysis requests"]
    FIXED --> LOGS["Bounded stages, safe errors and cancellation"]
    LOGS --> ENVUI
```

`web/environment_specs.py` owns the six allowlisted components and dependencies.
`environment_storage/paths/config/queue` separate persistence, approved storage,
configuration publication and lifecycle. Dedicated worker modules handle fixed
downloads/archives/commands and CPU probes. There is no arbitrary package manager
API or second process-ownership implementation. The metadata GET never imports
scientific SDKs or downloads. Inspection and installation are explicit durable jobs.

`tools/build_environment_resources.py` derives the base-worker requirements from
the sole application `uv.lock` using pinned uv 0.11.31; CI enforces parity. DECIMER
Python 3.10 and ADMET Python 3.12 CPU recipes describe separate scientific runtime
boundaries. Their locks and model fingerprints are packaged text, never model
binaries or user patents. All installations, downloads and state stay external.

Interpreter and model consumers read one external configuration. Every extraction
process captures its configuration at startup, so verified activation cannot
mix environments mid-run. Analysis publication serializes with the existing busy
gate and refreshes future runtime/cache identity. Manual changes and explicit
environment overrides cannot be silently replaced. None of these operations
changes scientific acceptance, original PDFs or generated results.

## Formal data flow

Every numbered page remains in original-PDF coordinates. The production chain never switches to a truncated PDF.

```mermaid
flowchart LR
    PDF["Original patent PDF"] --> C["1. Deterministic classify<br/>OCR cache + page classes"]
    C --> A["2. Activity extraction<br/>authoritative compounds and order"]
    A --> L["3. Structure-page locator<br/>active compounds only"]
    C --> L
    L --> S["4. DECIMER segmentation<br/>confirmed locator pages only"]
    S --> B["5. Structure binding<br/>visual evidence + activity order"]
    A --> B
    B --> O["6. DECIMER OCSR<br/>RDKit and chemistry QC"]
    O --> E["7. Excel and SDF export"]
    A --> E
    E --> DQ["8. Deterministic QA<br/>sole formal acceptance authority"]
    DQ -->|"acceptance.ok=true"| ACCEPT["Accepted deliverables"]
    DQ -->|"strict failure"| REJECT["STRICT_ACCEPTANCE_FAILED.json"]
    DQ -. "metrics only" .-> LLM["Optional LLM advisory QA"]
    LLM -.-> ADVICE["llm_qa_report.json / .md"]
```

The optional LLM report can suggest review but cannot promote, veto or mutate formal acceptance. Missing credentials produce an explicit `skipped_no_credentials` advisory artifact and do not degrade deterministic execution.

## Formal versus diagnostic paths

| Surface | Role | Formal-output authority |
|---|---|---|
| `run` | Complete activity-led pipeline | Yes, only when deterministic `acceptance.ok=true` |
| `classify`, `activity`, `smiles`, `qa` | Stage-level tools using current contracts | No by themselves |
| `excerpt`, `validate`, `score` | Diagnostics and operator investigation | No |
| `excerpt` output | Optional review PDF | Never consumed by the formal chain |

The ambiguous standalone `profile` and `bind` CLI paths are not exposed. Production bindings are tagged `execution_mode=production_activity_led`; production SMILES are tagged `execution_mode=production_decimer`.

## Artifact and failure contracts

Formal JSON artifacts carry the same identity envelope:

```json
{
  "schema": {"name": "patentsar.bindings", "version": 2},
  "product": {"name": "X-PatentSAR", "version": "0.1.0"},
  "pipeline_contract": {"name": "patentsar.activity-led", "version": "2.0.0"},
  "ruleset": {"name": "patentsar.accuracy-first", "version": "2.0.3"}
}
```

`smiles_results.json` is a versioned object with a `records` array; an unversioned bare list is not a reusable formal artifact. Cache reuse requires exact identity plus PDF, dependency and parameter fingerprints.

All fail-closed stages use one marker name and one writer: `STRICT_ACCEPTANCE_FAILED.json`. A successful formal QA clears that marker. There are no stage-specific failure filenames with conflicting meanings.

## Version model

| Identifier | Current value | Change trigger |
|---|---:|---|
| Product | `0.1.0` | User-visible software release |
| Pipeline contract | `patentsar.activity-led` `2.0.0` | Stage order or cross-stage semantics |
| Ruleset | `patentsar.accuracy-first` `2.0.3` | Acceptance or binding behavior |
| Artifact/cache schema | Namespaced integer versions | Serialized shape or cache compatibility |

Current non-default schema revisions are page classification v2 (`candidate_pages` replaces the ambiguous `core_pages` field), bindings v2 and formal QA v2. The diagnostic review-excerpt metadata starts at v1. All other current artifact/cache schemas are v1.

`contracts.py` is the only authority. Pipeline contract 2.0 removes the unused core-PDF branch and hidden worker profiling. Ruleset 2.0 makes deterministic QA the sole acceptance authority and explicitly separates diagnostic output. Ruleset 2.0.1 fixes spatial duplicate handling and strengthens ambiguity rejection; it invalidates old rule-dependent stage fingerprints without changing the product version or serialized schemas.

### Shared original-table observations and numbered cells

`core/table_geometry.py` is the single grid/coordinate OCR authority;
`core/table_cells.py` owns bounded cell observations and printed-cross counting.
`core/biology_tables.py` maps actual assay headers to cell values, while
`core/numbered_structure_binding.py` matches printed IDs to unique contained
DECIMER segments. Neither consumer imports the other or reconstructs flattened
page text into a competing row sequence. Tall structure rows require complete
vertical grid connections, rather than a fixed activity-row-height assumption.

Recognized pages leave generic OCR and repair paths, including when evidence is
withheld. A valid serialized cell proof is rechecked by the shared strict binding
rules; missing segments, ambiguous ownership and exact suffix conflicts fail.
`activity_sources` retains per-metric original pages/cells and observed assay
context. The Web adapter validates and reads this evidence without running OCR.

`core/structure_catalogs.py` scopes numbered cells to explicit catalog captions.
A catalog labelled selected/subset is ignored as a reprint only when all its
observed IDs exist in a non-subset catalog. Two full catalogs and selected tables
with novel IDs still compete and cannot silently erase conflicting evidence.
`core/visible_structure_binding.py` owns complete prefixed diagram captions on
non-table pages. Exact suffixes, original geometry and independently agreeing
cell observations are required; a parent number never supplies an isomer suffix.
When these spatial sources cover the entire active set with confirmed unique
images, generic crop OCR and multi-pass repair are bypassed. All source layouts
publish through `core/binding_artifacts.py` and the same downstream strict gate.
The writer also carries the input patent identity into each row; uploaded-file
names are never substituted as patent identifiers downstream.

Production OCSR has one raw-observation path. It does not rewrite atom symbols,
ring digits, disconnected components, isotope labels or stereochemistry. The
independent OCSR observation epoch namespaces exact-image cache entries; old
postprocessed entries remain on disk but are not promotable. A non-clean raw
prediction permits at most one explicitly enabled same-image normalization retry,
with both image hashes, source variants and unmodified strings retained. No second
engine or string repair becomes an acceptance authority. Normalization uses bounded
dimensions and atomic private output with explicit error reporting.

Ruleset 2.0.3 requires successful owned producers and newly published outputs:
worker errors or unchanged files cannot stamp a new manifest. The read model
projects only core-confirmed stages; failed-stage materials require an explicit
fresh-output fact. Copied pending artifacts are never current chemistry. Earlier
derived artifacts remain read-only history, not new formal acceptance.

Ruleset 2.0.2 previously invalidated derived artifacts. Raw OCR has an independent observation
contract: unchanged, PDF-SHA-verified 2.0.1 observations may seed a new run, but
2.0.0 text-only observations and old activity/binding/SMILES/QA cannot. The job
controller accepts reusable caches only inside the same private project. It
starts the same CLI with `--reuse-ocr-cache`; there is no second recovery pipeline.
Original failed runs are immutable inputs to this reuse step, not rewritten jobs.
Verified 2.0.1/2.0.2 raw observations may also seed 2.0.3; no old derived QA is promoted.
The pipeline persists actual stage starts and exception failures for the UI.
The queue projects completed current checkpoints into the existing SQLite
read model while a job runs. The UI refreshes on job/stage revisions, not on
every duration tick. This is presentation of provisional output, never another
extraction or acceptance path. A new job ID cannot retain previous-run rows.

### I-series structure-table evidence

`core/series_table_binding.py` owns the pure geometry/number-resolution rule; `structure_binder.py` calls it and serializes its typed evidence. OCR repeats within two PDF points of the same number are deduplicated, but the same printed number at a different row is preserved. Pairing requires mutually unique nearest geometry; ties, nonfinite or inverted boxes are withheld. Missing segmentation cannot shift later rows.

Shared page-cache extraction uses one `_page_payload` path for sequential and threaded builds/updates. Scanned RapidOCR/PaddleX pages store text and coordinates from the same inference, even when text is long. Native text pages skip OCR engine startup. Explicit text-only OCR backends do not fabricate coordinates.

Step-cache reuse validates both the current manifest identity envelope and its content fingerprint, including classification. An unchanged classification fingerprint cannot bypass a ruleset change and retain an old text-only OCR cache.

A printed-number correction requires a duplicated source ID, unique immediately adjacent observed anchors proving one missing integer, that integer in the activity set, and no occurrence of that integer anywhere else in the observed table. Anchors may cross an adjacent observed page boundary, but not a missing page. Original printed ID, coordinates, inferred ID and correction reason remain explicit. Unresolved duplicates, including unsegmented competing rows, are withheld. I-series coordinate pairing works independently on observed table pages even when the locator page list is discontinuous; only the numeric global-sequence rule requires a contiguous full table. Recognized I-series tables cannot fall through to that numeric rule when geometry is ambiguous.

## Removed ambiguous paths

- Automatic `core.pdf` generation: removed because downstream stages always used the original PDF and page indices could not safely cross documents.
- LLM page reclassification: removed because it could non-deterministically mutate page ownership and previously dropped the classification identity envelope.
- LLM writes to `final_qa_report.md`: replaced by separate `llm_qa_report.*` artifacts.
- LLM veto of deterministic acceptance: removed; advisory warnings are audit information only.
- Worker-side `PatentProfiler` fallback: removed; structure extraction accepts only locator-confirmed pages.
- Automatic repair recursion: removed because strict default gates aborted before most repair triggers and output invalidation was not a trustworthy recovery protocol.
- MolNexTR/MolVec fallback adapters: removed; production and stage-level OCSR are DECIMER-only.
- Bare SMILES JSON and `SMILES_ACCEPTANCE_FAILED.json`: replaced by the canonical SMILES envelope and single strict-failure marker.
- Unreferenced single-image DECIMER subprocess: removed; one bounded printed-model JSONL carrier owns recognition.
- Unlabelled `Structure-*` sequence generation and duplicate-name suffix fabrication: removed; missing/conflicting original IDs remain evidence gaps for strict arbitration.

## Runtime boundaries

The application uses locked CPython 3.12 dependencies. DECIMER runs as an isolated CPython 3.10 subprocess because its TensorFlow constraints do not support the application runtime. Child processes discard the parent's `PYTHONPATH`. `worker_bootstrap.py` loads only the calling first-party package by its exact location, so a stale installed copy cannot override it and the application's whole Python 3.12 site-packages never replaces native scientific dependencies. Conflicting already-imported packages fail explicitly.

`core/ocsr/printed_model.py` is the single recognition adapter for production,
research and environment probes. It verifies the pinned SDK sources, package
versions, official printed-model inventory and tokenizer digest before unpickling
or loading TensorFlow. It retains the SDK's original transforms and decoder without
eagerly loading the unused hand-drawn model. Segmentation remains separate; model
files already installed by an operator are not deleted.

One owned JSONL process serializes model inference. Image preparation has a bounded
window; `--smiles-workers` does not create additional TensorFlow models. CPU defaults
to two intra-operation/one inter-operation threads, with explicit compatible GPU
opt-in. Requests, response bytes, diagnostics, load/prediction deadlines and one
process restart are bounded. The 4096-MiB default resident budget monitors only this
worker, and insufficient model headroom fails before loading rather than stopping
other applications. Exact-image cache entries include model/SDK/adapter content and
execution-policy identity. Old repaired-string entries remain non-promotable.

Packaged defaults are immutable. Operator configuration belongs under `PATENTSAR_CONFIG_DIR` or the XDG config directory; run data belongs under an explicit output path, `PATENTSAR_STATE_DIR`, or the XDG state directory. No installed wheel writes into `site-packages`.

## Invariants

- Activity rows define the authoritative final-compound set and order.
- Production structure segmentation uses only locator-confirmed original-PDF pages.
- Final bindings are unique, current-version, strongly confirmed and production-tagged.
- Production OCSR is DECIMER-only; every accepted SMILES passes RDKit, query-atom and suspicious-element checks.
- A formal result requires `final_qa_report.json` with `acceptance.ok=true`.
- LLM/VLM responses are untrusted optional inputs and never control formal acceptance.
- A cache is reusable only when schema identity, PDF identity, dependencies and parameters match exactly.
