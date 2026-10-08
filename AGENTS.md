# PatentSAR Extractor engineering instructions

- Read `README.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/PROJECT_MANIFEST.md` before changing behavior or repository shape.
- Preserve fail-closed acceptance. Do not turn binding, SMILES, or QA errors into warnings to make a run appear successful.
- Production primary OCSR remains DECIMER. A maximum-eight-item local MolScribe pass is allowed only after primary cleanup for lost-stereo results with identical non-stereo graphs, preserved prior stereo, current original source QC and independently revalidated proof. It must not replace normal primary results or invent unspecified source stereochemistry.
- Keep credentials, patents, model weights, caches, logs, images, spreadsheets, and run directories out of Git.
- Every behavior change needs a regression test. Select checks from the exact diff and its affected consumers; do not run global tests without explicit user authorization. Deployment requires a clean wheel build, installed-wheel identity/health smoke, and the affected real-browser/API path. Do not disable required checks or branch protection to satisfy this scope.
- A task is delivered only after every task-related PR is merged into `main`, the exact merged revision is built and deployed, and post-deployment checks pass. A pushed branch or unmerged PR is not completion. Preserve a rollback wheel and external deployment evidence; never rewrite patent artifacts to make deployment pass.
- Product releases count merged PRs, not commits: patch 0–99 and minor 0–9, then carry into the next component. `contracts.__version__` is the sole authority; auto-prepared npm root versions and CI must agree. Update a stale PR to current main before merging; do not freeze v0.1.0, double-increment repeat events, change scientific epochs for a label-only release, or retag historical producer evidence. See `docs/OPERATIONS.md` for the single version workflow.
- Do not modify generated Excel/JSON/SDF files to bypass deterministic gates.
- Treat PDF, OCR, model output, environment paths and external HTTP responses as untrusted input.
