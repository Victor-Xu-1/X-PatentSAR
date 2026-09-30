# X-PatentSAR Web API v1

Controller-owned implementation contract. `contracts.py` owns product identity
and `patentsar.web-api` version 1. The local Web app presents the existing CLI
pipeline, never a second extraction chain. Manual reviews never alter generated
bindings, SMILES, or deterministic QA. Missing ADMET/LLM-summary capabilities are
explicitly unavailable, not populated with demonstration values.

## Security and storage

- Bind only to loopback (default port 8765). Validate Host and Origin; no wildcard CORS.
- `GET /api/v1/session` bootstraps a local same-origin session, sets an HttpOnly
  SameSite=Strict cookie, and returns `{csrf_token, user:{name}}`. Reject cross-site
  bootstrap. Authenticate every other API except non-sensitive `/health`.
- All writes require `X-CSRF-Token` bound to that session and a valid Origin.
- Use private operator-owned state, SQLite transactions and schema version 1;
  uploads, outputs, logs, sessions and reviews never belong in source/static/Git.
- Stream PDF uploads (128 MiB maximum), parse with real PyMuPDF, reject invalid,
  encrypted or over-limit PDFs. Do not accept arbitrary filesystem paths in HTTP.
- CLI-only run import permits an operator-selected existing directory, read-only.
  Validate asset paths under that directory; never serve arbitrary paths/symlinks.
- Default extraction concurrency is 1, bounded job lifetime and CPU threads.
  Cancel/recover only verified owned processes; never shut down WSL or C-disk jobs.
- Manual review uses revision checks (409 conflicts), separate audit history,
  and does not promote formal acceptance. Escape CSV formula-leading content.
- Responses never disclose credentials, arbitrary filesystem paths or tracebacks.

## Response models (snake_case)

`Project`:
`{id,title,patent_id,created_at,updated_at,pdf:{available,page_count,sha256},
is_historical,summary:{structures,activity_rows,matched_structures,confirmed,
needs_review},acceptance:{state,errors},last_job}`.
Acceptance states: `not_run`, `accepted`, `failed`, `historical`.
`accepted` requires current core identity and deterministic `acceptance.ok=true`;
old or incomplete artifacts must remain review/historical.

`Compound`:
`{id,display_id,structure_id,structure_image_url,smiles,activities,source,
confidence,review,flags}`. IDs preserve the authoritative activity compound ID.
`activities`: `[{name,value,unit,target,assay,page}]` (nullable optional metadata).
`source`: `{page,paragraph,bbox,source_label,correction_reason}`.
`confidence`: `{level,score,reason}`; levels `high`, `medium`, `review`, `unknown`.
Do not invent numerical confidence; score may be null. Old identity is not current
high confidence. `review`: `{decision,note,revision,updated_at}` or null.

`Page`:
`{page,page_count,width,height,image_url,text,source_mode,annotations}`.
`source_mode`: `native`, `ocr`, `historical`, `unavailable`.
`annotations`: `[{compound_id,bbox,kind,verified}]`; bbox is rendered-page PDF
points and must account for rotation. Missing original PDF has null image_url;
historical OCR remains explicitly historical, never a fabricated original page.

`Job`:
`{id,project_id,status,created_at,started_at,finished_at,error,stages,can_resume}`.
Statuses: `queued`, `running`, `complete`, `failed`, `cancelled`, `interrupted`.
`error`: `{code,message}` or null. `stages`:
`[{name,status,count,duration_seconds}]` for the real stages
`classify,activity,locate,structures,bind,smiles,final,qa`.
Stage statuses: `pending,running,ok,empty,failed,warnings`.
Job completion is not necessarily formal QA acceptance. No guessed 100% progress.

Errors: `{error:{code,message}}`, with appropriate 400/401/403/404/409/413/422/500.
No swallowed failures or success-shaped error responses.

## Endpoints

| Method / path | Request and response |
|---|---|
| GET `/health` | `{product,schema,ruleset,ready,capabilities:{admet:false,summary:false}}` |
| GET `/session` | Same-origin bootstrap, CSRF token and session cookie |
| GET `/projects` | `{items:Project[]}` |
| POST `/projects?filename=&title=` | Raw `application/pdf` body -> Project (201) |
| GET `/projects/{id}` | Project |
| POST `/projects/{id}/pdf?filename=` | Attach raw original PDF to historical import; verify expected source SHA before accepting |
| GET `/projects/{id}/pages/{page}` | Page, one-based bounded page number |
| GET `/projects/{id}/pages/{page}/image?scale=1.5` | Actual PNG, bounded scale/pixels/concurrency |
| GET `/projects/{id}/structures/{compound_id}/image` | Actual safe crop PNG; missing image is 404 |
| GET `/projects/{id}/results?q=&confidence=&review=&target=&page=1&page_size=10` | `{items:Compound[],total,page,page_size,metrics:string[],targets:string[]}`; max page_size 100 |
| POST `/projects/{id}/jobs` | `{allow_partial:false,advisory:false,resume_job_id:null}` -> Job (202); default no paid advisory requests |
| GET `/jobs?project_id=` | `{items:Job[]}` |
| GET `/jobs/{id}` | Persisted Job and current real stage states |
| POST `/jobs/{id}/cancel` | Idempotent owned-job cancellation -> Job |
| PUT `/projects/{id}/reviews/{compound_id}` | `{decision,note,expected_revision}` -> Review; decisions `approved,rejected,needs_review`; first revision 0 |
| POST `/projects/{id}/export` | `{format:"csv" or "json",compound_ids:[]}` -> actual download; empty IDs means filtered/all rows, clearly review-only unless formally accepted |
| GET `/runtime` | `{product,storage:{state_root,platform},interpreters:[{role,configured,available}],capabilities}`; no secrets |

All paths in the table are relative to `/api/v1`. Frontend API adapters use these
names; changes require controller review, not independent endpoint invention.

## Frontend behavior

Chinese UI with X-PatentSAR branding and version from `/health`; reference layout:
232 px left navigation, compact breadcrumb/search toolbar, split original PDF
and result workspace, warm ivory canvas, quiet stone surfaces, ink controls,
terracotta accents, serif display headings, real metric cards and dense
compound/activity rows. Page navigation, zoom, text/annotation tabs, source jumps,
search/filter/pagination, selection/export, review dialogs, job status/cancel/retry,
project/PDF import and runtime settings must work, including empty/error/loading,
keyboard/focus, refresh/deep-link and smaller viewport states. Unavailable ADMET
has a clear disabled/informational state. No fictional molecules, assays or counts.

## Implementation and validation plan

1. Complete: implement the API and reference-layout UI in isolated worktrees,
   and integrate CLI entry points, packaging and E-drive launchers.
2. Complete: unify all pages and dialogs with the Claude-inspired light visual
   system, preserving X-PatentSAR identity; verify tokens, typography, controls,
   real data, keyboard interactions and representative viewports in Chromium.
3. Locally complete: build the Web assets and wheel from a clean revision, verify
   independent installed startup, security boundaries and all ten browser checks,
   and push the authorized private Apache-2.0 repository. GitHub Actions cannot
   start its runner because the account reports failed payments or a spending
   limit; remote CI is not marked passed. No account billing settings are changed.

### Complete task workflow iteration

1. Complete: recover the actual WO2026156070 original from local file storage,
   copy it to E and attach it only after its recorded SHA-256 matches exactly.
   The 1,553 pages and source page 361 render through the real parser/API.
2. In progress: add a full task input page, retained real job parameters,
   results-first/resizable/fullscreen layouts, local DECIMER crop recognition,
   ADMET-AI v2 CPU inference and source-grounded deterministic evidence summaries.
3. Pending: run affected tests and the mandatory packaging/runtime gates against
   a clean candidate, deploy to E, verify the actual original and data in Chromium,
   and push the private repository. No global WSL shutdown or user-data cleanup.

Additional API v1 contract (all additive; current product remains v0.1.0):

- POST `/projects` additionally accepts optional `patent_id` query metadata.
  Empty metadata keeps filename inference; validate a bounded normalized ID.
- POST `/projects/{id}/jobs` additionally accepts `include_intermediates:false`,
  `force:false`, `task_note:""` (max 2,000 characters). They are retained in the
  existing immutable job specification; notes are operator records, not executed
  instructions. The existing strict QA default and opt-in advisory flag stay.
  Job responses add the same three fields. Resume preserves original options
  and notes, never silently re-enables force or paid model calls.
- POST `/analysis/admet` accepts `{smiles:[string]}` (1–50 bounded, chemically
  valid canonical molecules) and returns `{engine:{name,version,model_sha256},
  generated_at,review_only:true,predictions:[{smiles,properties:[{key,label,value,
  unit,kind:"descriptor" or "prediction"}]}],warnings:[]}`. Values must come from
  actual RDKit calculations or ADMET-AI v2 model inference, not heuristic ADMET
  substitutes. Probabilities and endpoint units stay explicit.
- POST `/projects/{id}/compounds/{compound_id}/recognize` has an empty JSON body
  and returns `{compound_id,status:"recognized" or "rejected",smiles,engine:
  {name,version},warnings:[],review_only:true}`. It reads the real bounded crop,
  reuses DECIMER and RDKit QC and stores analysis separately; it must not overwrite
  generated bindings, pipeline SMILES, confidence or formal acceptance.
- GET `/projects/{id}/evidence-summary` returns `{project_id,generated_at,
  acceptance,counts:{structures,activity_rows,compounds,smiles,source_located,
  needs_review},activities:[{name,unit,rows,numeric_rows,min,max,censored_rows,
  target}],targets:[{name,rows}],limitations:[],source_pages:[]}`. Aggregate only
  original fields, preserve censored/range values and provenance, and do not
  merge incomparable units/targets. This is deterministic evidence summarization,
  not an LLM mechanism/efficacy claim.
- `/health` and `/runtime` expose real `admet`/`summary` capabilities; the analysis
  integration does not add a second HTTP app or core extraction authority.

Heavy analysis runs in a bounded, one-consumer CPU subprocess boundary using
operator-selected external environments, models and E-drive caches. Prediction
and recognition caches are private rebuildable analysis state, independently
versioned; the authoritative project/job/review SQLite schema stays unchanged.
Model/environment absence, timeout, invalid molecules, rejection and concurrent
requests must be visible failures, not silent degradation. No remote molecule
upload, paid service, proprietary model or credential is introduced by default.

Validation mapping: task form → upload/parse, persistent job options, actual CLI
arguments and queue/cancellation; original PDF → exact SHA, real page images,
source jump and annotation coordinates; layout → larger measured result-table
area, splitter keyboard/pointer, fullscreen and mobile; DECIMER/ADMET → real
model inference, QC, bounded concurrency/timeout, invalid input and cache
identity; evidence summary → real rows, units/censoring, limits and historical
acceptance unchanged. LLM remains opt-in and outside this deterministic summary.

The single visual authority is `frontend/src/styles/tokens.css`. Component styles
consume those tokens, not page-specific palettes or layered legacy themes. The
reference is Claude's public light workspace style; X-PatentSAR is independent
and uses system/open fonts, not Claude trademarks or proprietary font files.
Design acceptance covers canvas/sidebar/ink/terracotta colors, neutral active
navigation, serif headings, compact controls, warm tables/dialogs, focus and
contrast, desktop/mobile overflow and actual PDF/result workflows. Pixel-perfect
identity to a particular Claude release requires a user-supplied reference image.

Change-to-validation mapping: PDF upload and rendering require a real PyMuPDF
parse, bounded invalid-input checks and original-page source jumps; project/job
storage requires real SQLite persistence, cancellation and restart recovery;
manual review requires revision-conflict tests and unchanged generated artifacts;
exports require selection, acceptance labeling and CSV formula checks; session
and static serving require Host/Origin/CSRF, path and secret-disclosure checks;
UI requires loading/empty/error states, keyboard interactions, navigation/refresh
and representative desktop/mobile layouts. Existing core unit, wheel and real-PDF
gates remain required. No new LLM feature is introduced by this presentation work.

The portable CLI defaults to 8765. This workstation uses 18765 because 8765 and
8766 are already occupied by other applications. Source, environments, models,
state, build evidence and development caches remain on the E-drive WSL system.

Current integration evidence: 142 Python tests and 80 frontend tests passed;
all ten real Chromium workflow/style checks passed against the local stack. The separate
real WO2026156070 history workflow also passed with immutable source artifacts.
Its 1,189 structures, 1,157 activity rows and 1,156 compounds remain historical;
the original PDF is absent and no formal acceptance is claimed. The independent
installed E-drive deployment also passed all ten workflow/style checks and three
additional read-only checks with the actual WO2026156070 historical dataset.
Deployment evidence, screenshots and wheel/revision checksums live outside Git
under the operator's E-drive evidence directory.
