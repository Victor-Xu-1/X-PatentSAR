# PatentSAR Extractor engineering instructions

- Read `README.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/PROJECT_MANIFEST.md` before changing behavior or repository shape.
- Preserve fail-closed acceptance. Do not turn binding, SMILES, or QA errors into warnings to make a run appear successful.
- Production OCSR remains DECIMER-only unless a reviewed contract change includes representative real-patent evidence.
- Keep credentials, patents, model weights, caches, logs, images, spreadsheets, and run directories out of Git.
- Every behavior change needs a regression test. Run compileall, the complete unittest suite, wheel build, installed-wheel smoke, and an applicable real-PDF path.
- Do not modify generated Excel/JSON/SDF files to bypass deterministic gates.
- Treat PDF, OCR, model output, environment paths and external HTTP responses as untrusted input.
