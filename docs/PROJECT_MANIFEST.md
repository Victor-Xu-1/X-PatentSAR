# Project governance manifest

- Product/repository identity: `x-patentsar` / X-PatentSAR; current stable E-drive WSL source path `/srv/wsl/projects/patent-sar-extractor` (preserved through branding). Internal Python namespace remains `patent_sar_extractor`; it is not a competing product identity.
- Product version authority: `src/patent_sar_extractor/contracts.py`; current release `v0.1.0`; Semantic Versioning; release tags use `vMAJOR.MINOR.PATCH`.
- Internal contract authority: the same `contracts.py` file separately owns pipeline contract `2.0.0`, ruleset `2.0.1`, and artifact/cache schema identities.
- Supported source roots: `src/patent_sar_extractor`, `frontend`, `examples`, `docs`, `tests`, `.github` and documented root metadata/launch files, including Apache-2.0 `LICENSE` and attribution `NOTICE`.
- Dependency authority: `pyproject.toml` plus generated `uv.lock`; uv 0.11.31 is the verified lock/sync tool, matching CI. DECIMER is an external Python 3.10 runtime boundary and is not part of the Python 3.12 application lock.
- Public contract: the `x-patentsar` CLI, `PATENTSAR_*` configuration variables and documented output files; Web API uses an independently versioned `patentsar.web-api` v1 contract. A Web result/review never overrides deterministic QA.
- Runtime state: operator-selected output paths, `PATENTSAR_STATE_DIR`, or the XDG state directory; runtime data never belongs in source or `site-packages`.
- Generated output: wheels and source archives are created under ignored `dist/` and must be reproducible from an identified clean revision.
- Vendored/model assets: none. DECIMER and OCR model assets are externally installed and retain their upstream licenses.
- Branch policy: task branch and isolated worktree for future concurrent work; `main` is the integration branch once a remote is configured.
- Required checks: compileall, complete unittest suite, frozen dependency sync, wheel-content audit, isolated installed-wheel CLI/config smoke, environment health and representative real-PDF smoke.
- Rollback: stop the new process and restore the previous executable/path; never mutate existing run directories during rollback.
- Recovery baseline: the restored checkout has an unborn `main`, no commits and no remote. Source is preserved as untracked user work plus external archives. This is not yet a clean-clone/release baseline; no GitHub publication has been performed.
