# PatentSAR Extractor engineering instructions

- Read `README.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/PROJECT_MANIFEST.md` before changing behavior or repository shape.
- Preserve fail-closed acceptance. Do not turn binding, SMILES, or QA errors into warnings to make a run appear successful.
- Production OCSR remains DECIMER-only unless a reviewed contract change includes representative real-patent evidence.
- Keep credentials, patents, model weights, caches, logs, images, spreadsheets, and run directories out of Git.
- Every behavior change needs a regression test. Select checks from the exact diff and its affected consumers; do not run global tests without explicit user authorization. Deployment requires a clean wheel build, installed-wheel identity/health smoke, and the affected real-browser/API path. Do not disable required checks or branch protection to satisfy this scope.
- A task is delivered only after every task-related PR is merged into `main`, the exact merged revision is built and deployed, and post-deployment checks pass. A pushed branch or unmerged PR is not completion. Preserve a rollback wheel and external deployment evidence; never rewrite patent artifacts to make deployment pass.
- Do not modify generated Excel/JSON/SDF files to bypass deterministic gates.
- Treat PDF, OCR, model output, environment paths and external HTTP responses as untrusted input.
