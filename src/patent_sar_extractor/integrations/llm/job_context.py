"""One immutable API policy and persistent quota for a logical resumable job."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .config import EvidenceResolutionConfig
from .credential_authorization import authorized_key, credential_digest
from .private_state import private_root, read_budget, read_private, write_private

CONTEXT_SCHEMA = {"name": "patentsar.llm-job-context", "version": 2}
LEGACY_CONTEXT_SCHEMA = {"name": "patentsar.llm-job-context", "version": 1}
JOB_ID = re.compile(r"[a-f0-9]{32}")


@dataclass(frozen=True)
class JobLLMContext:
    job_id: str
    original_sha256: str
    policy: EvidenceResolutionConfig
    root: Path

    @property
    def ledger(self) -> Path:
        return self.root / f"{self.job_id}.budget.json"


def create_context(
    workspace: Path, job_id: str, original_sha256: str, policy: EvidenceResolutionConfig
) -> Path:
    policy.validate()
    if not JOB_ID.fullmatch(job_id) or not re.fullmatch(
        r"[a-f0-9]{64}", original_sha256
    ):
        raise ValueError("Invalid original/job LLM identity")
    root = private_root(workspace / "llm")
    # Off cannot carry an accidental enabling fallback or disclose a stored key.
    if policy.mode == "off" or not policy.data_consent:
        policy = replace(policy, endpoint="", api_key="", model="", cache_path="")
    else:
        policy = replace(policy, cache_path=str(root / "responses.sqlite3"))
    path = root / f"{job_id}.policy.json"
    if path.exists() or path.is_symlink():
        raise FileExistsError("Immutable LLM context already exists")
    write_private(
        root / f"{job_id}.budget.json",
        {"job_id": job_id, "limit": policy.max_calls, "calls": 0},
        exclusive=True,
    )
    recorded_policy = asdict(policy)
    reference = ""
    if policy.authorization_file and policy.mode != "off" and policy.data_consent:
        reference = credential_digest(policy.api_key)
        recorded_policy["api_key"] = ""
    write_private(
        path,
        {
            "schema": CONTEXT_SCHEMA,
            "job_id": job_id,
            "original_sha256": original_sha256,
            "policy": recorded_policy,
            "credential_sha256": reference,
        },
        exclusive=True,
    )
    return path


def read_context(value: str | Path) -> JobLLMContext:
    path = Path(value)
    packet = read_private(path)
    legacy = packet.get("schema") == LEGACY_CONTEXT_SCHEMA
    fields = {"schema", "job_id", "original_sha256", "policy"}
    if not legacy:
        fields.add("credential_sha256")
    if set(packet) != fields:
        raise ValueError("Invalid immutable API context")
    job_id, original = packet["job_id"], packet["original_sha256"]
    if (
        packet["schema"] not in (CONTEXT_SCHEMA, LEGACY_CONTEXT_SCHEMA)
        or not isinstance(job_id, str)
        or not JOB_ID.fullmatch(job_id)
        or path.name != f"{job_id}.policy.json"
        or not isinstance(original, str)
        or not re.fullmatch(r"[a-f0-9]{64}", original)
        or not isinstance(packet["policy"], dict)
    ):
        raise ValueError("Foreign or malformed API context")
    policy = EvidenceResolutionConfig(**packet["policy"])
    if policy.authorization_file and policy.mode != "off" and policy.data_consent:
        # Validate semantics without duplicating the private key in a new snapshot.
        replace(policy, api_key="credential-reference-validation").validate()
        reference = (
            credential_digest(policy.api_key) if legacy else packet["credential_sha256"]
        )
        key = authorized_key(path.parent, job_id, original, policy, reference)
        policy = replace(policy, api_key=key)
    else:
        policy.validate()
        if not legacy and packet["credential_sha256"]:
            raise ValueError(
                "An inactive/operator policy cannot carry a GUI credential reference"
            )
    read_budget(path.parent / f"{job_id}.budget.json", job_id, policy.max_calls)
    if policy.cache_path and policy.cache_path != str(
        path.parent / "responses.sqlite3"
    ):
        raise ValueError("API cache is outside its private workspace")
    return JobLLMContext(job_id, original, policy, path.parent)


def context_for_run(
    base_dir: str,
    original_sha256: str,
    *,
    policy: EvidenceResolutionConfig | None = None,
) -> JobLLMContext:
    from .job_health import ensure_attempt_id

    ensure_attempt_id()  # Inherit one identity across this CLI's isolated stages.
    configured = os.environ.get("PATENTSAR_LLM_CONTEXT", "")
    if configured:
        context = read_context(configured)
        if context.original_sha256 != original_sha256:
            raise ValueError("LLM task snapshot belongs to another original")
        return context
    from .config import get_evidence_resolution_config

    # Standalone attempts keep a private context separate from formal artifacts.
    job_id = hashlib.sha256(str(Path(base_dir).absolute()).encode()).hexdigest()[:32]
    control = Path(base_dir).absolute() / ".llm-control"
    path = control / "llm" / f"{job_id}.policy.json"
    if not path.exists():
        create_context(
            control, job_id, original_sha256, policy or get_evidence_resolution_config()
        )
    context = read_context(path)
    if context.original_sha256 != original_sha256:
        raise ValueError("Standalone API snapshot original changed")
    return context
