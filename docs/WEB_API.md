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
220–235 px left navigation, compact breadcrumb/search toolbar, split original PDF
and result workspace, blue accent, light borders, real metric cards and dense
compound/activity rows. Page navigation, zoom, text/annotation tabs, source jumps,
search/filter/pagination, selection/export, review dialogs, job status/cancel/retry,
project/PDF import and runtime settings must work, including empty/error/loading,
keyboard/focus, refresh/deep-link and smaller viewport states. Unavailable ADMET
has a clear disabled/informational state. No fictional molecules, assays or counts.
