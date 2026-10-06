"""Attempt ownership, write-once stage history and verified checkpoint transport.

Transport is not a cache authority: the sole CLI still rechecks its fingerprints,
parameters and acceptance gates after paths have been relocated to a new attempt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from patent_sar_extractor import contracts as core

from .errors import WebError
from .files import MAX_ARTIFACT_BYTES, MAX_RECORDS, SafeFiles, private_directory
from .models import STAGES, Stage
from .processes import RunSpec
from .stages import read_summary, recorded_stage_order, stages_from_summary
from .storage import Store, encode

logger = logging.getLogger(__name__)
ATTEMPT_VERSION = 1
MAX_HISTORY_BYTES = 65536
MAX_COPY_BYTES = 512 * 1024 * 1024
MAX_COPY_FILES = 25000
OCR_PATH = "page_classification/page_ocr_cache.json"
_CHECKPOINT_ARTIFACTS = {
    "classify": (
        "page_classification/page_classification.json",
        core.PAGE_CLASSIFICATION_SCHEMA,
        core.PAGE_CLASSIFICATION_SCHEMA_VERSION,
    ),
    "activity": (
        "activity/activity_data.json",
        core.ACTIVITY_SCHEMA,
        core.ACTIVITY_SCHEMA_VERSION,
    ),
    "locate": (
        "structure_pages/locator.json",
        core.STRUCTURE_LOCATION_SCHEMA,
        core.STRUCTURE_LOCATION_SCHEMA_VERSION,
    ),
    "structures": (
        "structures/metadata.json",
        core.STRUCTURES_SCHEMA,
        core.STRUCTURES_SCHEMA_VERSION,
    ),
    "bind": (
        "structure_bindings/bindings.json",
        core.BINDINGS_SCHEMA,
        core.BINDINGS_SCHEMA_VERSION,
    ),
    "smiles": (
        "smiles/smiles_results.json",
        core.SMILES_SCHEMA,
        core.SMILES_SCHEMA_VERSION,
    ),
}
# Artifact declarations are paths, never a second execution-order authority.
# Final outputs/QA remain absent: copying checkpoints cannot copy acceptance.
ARTIFACTS = {
    name: _CHECKPOINT_ARTIFACTS[name]
    for name in core.CORE_STAGE_ORDER
    if name in _CHECKPOINT_ARTIFACTS
}
DEPENDENCIES = {item[0] for item in ARTIFACTS.values()} | {
    OCR_PATH,
    "structure_pages/crop_regions.json",
}
IMAGE_KEYS = {
    "image_path",
    "source_image_path",
    "ocsr_image_path",
    "ocsr_structure_image",
    "structure_image",
    "input_image",
}
PATH_KEYS = IMAGE_KEYS | {"ocr_cache_path", "output", "output_dir"}


def spec_record(raw: str) -> dict[str, Any]:
    try:
        if len(raw) > MAX_HISTORY_BYTES:
            raise ValueError("oversized specification")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise TypeError("invalid specification")
        preparation = payload.get("checkpoint_preparation", "ready")
        source_job = payload.get("checkpoint_source_job_id")
        if (
            not isinstance(preparation, str)
            or preparation not in {"preparing", "ready"}
            or (
                source_job is not None
                and (
                    not isinstance(source_job, str)
                    or not re.fullmatch(r"[a-f0-9]{32}", source_job)
                )
            )
            or (preparation == "preparing" and source_job is None)
        ):
            raise ValueError("invalid checkpoint preparation")
        for name in (
            "job_id",
            "project_id",
            "pdf_path",
            "output_dir",
            "patent_id",
            "sha256",
        ):
            value = payload.get(name)
            # An original can lack a readable patent identifier. Preserve the
            # unknown value; PDF ownership remains anchored by its exact SHA.
            minimum_length = 0 if name == "patent_id" else 1
            if (
                not isinstance(value, str)
                or not minimum_length <= len(value) <= 4096
                or any(
                    ord(character) < 32 or ord(character) == 127 for character in value
                )
            ):
                raise ValueError("invalid specification field")
        for name in (
            "advisory",
            "allow_partial",
            "include_intermediates",
            "force",
            "include_admet",
            "admet_only",
        ):
            if name in payload and type(payload[name]) is not bool:
                raise ValueError("invalid specification option")
        compounds = payload.get("admet_compounds", [])
        if (
            not isinstance(compounds, list)
            or len(compounds) > 100
            or any(
                not isinstance(value, str)
                or not 1 <= len(value) <= 200
                or any(ord(c) < 32 for c in value)
                for value in compounds
            )
            or len(set(compounds)) != len(compounds)
            or (payload.get("admet_only") and not payload.get("include_admet"))
        ):
            raise ValueError("invalid prediction specification")
        note = payload.get("task_note", "")
        source = payload.get("source_ocr_cache", "")
        if (
            not isinstance(note, str)
            or len(note) > 2000
            or any(
                ord(character) < 32 and character not in "\t\n\r" for character in note
            )
            or "\x7f" in note
            or not isinstance(source, str)
            or len(source) > 4096
            or any(ord(character) < 32 or ord(character) == 127 for character in source)
        ):
            raise ValueError("invalid specification metadata")
        return payload
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise WebError(
            409, "invalid_job_record", "Persisted job specification is invalid."
        ) from exc


@dataclass(frozen=True)
class StageHistory:
    available: bool
    stages: list[Stage]
    stage_order: list[str] | None = None


class AttemptHistory:
    def __init__(self, store: Store) -> None:
        self.store = store

    def output(self, row: dict[str, Any]) -> Path | None:
        """Open every directory component without following symlinks."""
        try:
            spec = spec_record(row["spec"])
            raw = spec.get("output_dir")
            if not isinstance(raw, str) or not raw or "\\" in raw or "\0" in raw:
                return None
            path = Path(raw)
            project_root = self.store.root / "runs" / row["project_id"]
            relative = path.relative_to(self.store.root)
            if (
                not path.is_relative_to(project_root)
                or path == project_root
                or str(path) != raw
                or any(part in {".", ".."} for part in relative.parts)
                or spec.get("job_id") != row["id"]
                or spec.get("project_id") != row["project_id"]
                or (
                    "attempt_version" in spec
                    and (
                        type(spec["attempt_version"]) is not int
                        or spec["attempt_version"] != ATTEMPT_VERSION
                        or path != project_root / row["id"]
                    )
                )
            ):
                return None
            fd = os.open(self.store.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for part in relative.parts:
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                    os.close(fd)
                    fd = child
                info = os.fstat(fd)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                    return None
            finally:
                os.close(fd)
            return path
        except (OSError, ValueError, WebError):
            return None

    def unique(self, row: dict[str, Any]) -> bool:
        try:
            record = spec_record(row["spec"])
            output = record.get("output_dir")
        except WebError:
            return False
        if not isinstance(output, str):
            return False
        with self.store.connect() as connection:
            # Non-canonical paths never pass output(); malformed peers cannot
            # supply trustworthy ownership evidence for a legacy directory.
            if connection.execute(
                "SELECT 1 FROM jobs WHERE project_id=? AND id<>? AND "
                "(CASE WHEN json_valid(spec) THEN json_extract(spec,'$.output_dir')=? ELSE 1 END) LIMIT 1",
                (row["project_id"], row["id"], output),
            ).fetchone():
                return False
            if record.get("attempt_version") == ATTEMPT_VERSION:
                return True  # Exact owned job-ID directories cannot alias.
            # Old specifications permitted shared directories. Resolve peers
            # read-only to detect alternate spelling and symlink aliases too.
            for index, peer in enumerate(
                connection.execute(
                    "SELECT spec FROM jobs WHERE project_id=? AND id<>?",
                    (row["project_id"], row["id"]),
                )
            ):
                if index >= 10000:
                    return False
                try:
                    raw = spec_record(peer["spec"]).get("output_dir")
                    if not isinstance(raw, str) or Path(raw).resolve() == Path(output):
                        return False
                except (OSError, ValueError, WebError):
                    return False
            return True

    def observe(self, row: dict[str, Any], status: str | None = None) -> StageHistory:
        root = self.output(row)
        if root is None or not self.unique(row):
            return StageHistory(False, [])
        spec = spec_record(row["spec"])
        summary = read_summary(root)
        status = status or row["status"]
        if summary is None:
            available = (
                not os.path.lexists(root / "pipeline_summary.json")
                and spec.get("attempt_version") == ATTEMPT_VERSION
                and (status in {"queued", "running"} or not row["started_at"])
            )
            return StageHistory(
                available,
                [
                    Stage(name=name)
                    for name in (
                        core.CORE_STAGE_ORDER
                        if spec.get("runtime_identity")
                        == {
                            "product": core.product_ref(),
                            "pipeline_contract": core.pipeline_contract_ref(),
                            "ruleset": core.ruleset_ref(),
                        }
                        else STAGES
                    )
                ]
                if available
                else [],
                list(core.CORE_STAGE_ORDER)
                if available
                and spec.get("runtime_identity", {}).get("pipeline_contract")
                == core.pipeline_contract_ref()
                else None,
            )
        if (
            ("output_dir" in summary and summary["output_dir"] != str(root))
            or (
                "patent_id" in summary and summary["patent_id"] != spec.get("patent_id")
            )
            or ("input_pdf" in summary and summary["input_pdf"] != spec.get("pdf_path"))
            or (
                status == "complete" and summary["status"] not in {"complete", "review"}
            )
            or (
                status in {"failed", "cancelled", "interrupted"}
                and summary["status"] == "complete"
            )
        ):
            return StageHistory(False, [])
        return StageHistory(
            True,
            stages_from_summary(summary, SafeFiles(root)),
            recorded_stage_order(summary),
        )

    def read(self, row: dict[str, Any]) -> StageHistory:
        if not isinstance(row.get("id"), str) or not re.fullmatch(
            r"[a-f0-9]{32}", row["id"]
        ):
            return StageHistory(False, [])
        spec = spec_record(row["spec"])
        if spec.get("attempt_version") != ATTEMPT_VERSION or row["status"] in {
            "queued",
            "running",
        }:
            return self.observe(row)
        try:
            files = SafeFiles(self.store.root)
            payload = json.loads(
                files.read(f"job-history/{row['id']}.json", max_bytes=MAX_HISTORY_BYTES)
            )
            if (
                not isinstance(payload, dict)
                or payload.get("schema")
                != {"name": "patentsar.attempt-history", "version": 1}
                or payload.get("spec_sha256")
                != hashlib.sha256(row["spec"].encode()).hexdigest()
                or payload.get("status") != row["status"]
                or payload.get("finished_at") != row["finished_at"]
                or type(payload.get("available")) is not bool
                or not isinstance(payload.get("stages"), list)
                or len(payload["stages"]) > len(STAGES)
            ):
                return StageHistory(False, [])
            stages = [Stage.model_validate(value) for value in payload["stages"]]
            order = payload.get("stage_order")
            if order is not None and (
                not isinstance(order, list)
                or len(order) != len(STAGES)
                or not all(isinstance(v, str) for v in order)
                or set(order) != set(STAGES)
            ):
                return StageHistory(False, [])
            if payload["available"] and tuple(stage.name for stage in stages) != tuple(
                order or STAGES
            ):
                return StageHistory(False, [])
            return StageHistory(
                payload["available"],
                stages if payload["available"] else [],
                order,
            )
        except (WebError, ValueError, RecursionError, UnicodeError, ValidationError):
            return StageHistory(False, [])

    def seal(self, row: dict[str, Any], status: str, finished_at: str) -> None:
        if not isinstance(row.get("id"), str) or not re.fullmatch(
            r"[a-f0-9]{32}", row["id"]
        ):
            raise WebError(
                409,
                "invalid_job_record",
                "Job identity is not a safe history filename.",
            )
        if spec_record(row["spec"]).get("attempt_version") != ATTEMPT_VERSION:
            return  # Never invent a recoverable snapshot for old shared attempts.
        from .admet_history import read_admet_stage

        root = self.output(row)
        _, core_completed = read_admet_stage(row, root)
        # The CLI's completed facts remain genuine when its subsequent research
        # phase fails. Overall job failure is retained in the immutable envelope.
        history = self.observe(
            row,
            (
                "failed"
                if (read_summary(root) or {}).get("status")
                in {"failed_qa", "failed_accuracy_gate"}
                else "complete"
            )
            if core_completed and spec_record(row["spec"]).get("include_admet")
            else status,
        )
        directory = private_directory(self.store.root / "job-history")
        payload = encode(
            {
                "schema": {"name": "patentsar.attempt-history", "version": 1},
                "spec_sha256": hashlib.sha256(row["spec"].encode()).hexdigest(),
                "status": status,
                "finished_at": finished_at,
                "available": history.available,
                "stages": [stage.model_dump() for stage in history.stages],
                "stage_order": history.stage_order,
            }
        ).encode()
        if len(payload) > MAX_HISTORY_BYTES:
            raise WebError(
                413, "history_limit", "Attempt history exceeds its size limit."
            )
        fd = os.open(
            directory / f"{row['id']}.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())


@dataclass(frozen=True)
class VerifiedCheckpoint:
    stage: str
    path: str
    payload: dict[str, Any]
    manifest: dict[str, Any]


class CheckpointCopy:
    """A bounded, independent copy; never directory copying or hardlinks."""

    def __init__(
        self,
        source: Path,
        target: Path,
        *,
        check_cancel: Callable[[], None] | None = None,
    ) -> None:
        self.files = SafeFiles(source)
        self.source = source
        self.target = private_directory(target)
        self.content: dict[str, str] = {}
        self.total = 0
        self.check_cancel = check_cancel

    def put(self, relative: str, content: bytes) -> None:
        if self.check_cancel is not None:
            self.check_cancel()
        relative = str(self.files.relative(relative))
        if relative in self.content:
            return
        if (
            len(content) > MAX_ARTIFACT_BYTES
            or len(self.content) >= MAX_COPY_FILES
            or self.total + len(content) > MAX_COPY_BYTES
        ):
            raise WebError(
                413, "checkpoint_limit", "Verified checkpoints exceed the copy budget."
            )
        destination = self.target / relative
        parent = self.target
        # mkdir(parents=True, mode=0o700) applies mode only to the leaf; create
        # each transport-owned ancestor privately before any nested crop copy.
        for part in Path(relative).parts[:-1]:
            parent = private_directory(parent / part)
        fd = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        self.content[relative] = hashlib.sha256(content).hexdigest()
        self.total += len(content)

    def raw(self, relative: str) -> bytes:
        return self.files.read(relative, max_bytes=MAX_ARTIFACT_BYTES)

    def relocate(self, value: Any, *, depth: int = 0, path_field: bool = False) -> Any:
        if depth > 40:
            raise WebError(
                422, "checkpoint_limit", "Checkpoint nesting exceeds its limit."
            )
        if isinstance(value, str) and path_field and value:
            if value == str(self.source):
                return str(self.target)
            if (
                value.startswith(str(self.source) + "/")
                or not Path(value).is_absolute()
            ):
                return str(self.target / self.files.relative(value))
        if isinstance(value, list):
            return [self.relocate(item, depth=depth + 1) for item in value]
        if isinstance(value, dict):
            # Only declared path fields move. Chemical strings, raw model
            # observations, model fingerprints and other provenance stay exact.
            return {
                key: self.relocate(item, depth=depth + 1, path_field=key in PATH_KEYS)
                for key, item in value.items()
            }
        return value

    def images(self, payload: Any, *, depth: int = 0) -> None:
        if depth > 40:
            raise WebError(
                422, "checkpoint_limit", "Checkpoint nesting exceeds its limit."
            )
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in IMAGE_KEYS and value:
                    if not isinstance(value, str):
                        raise WebError(
                            422,
                            "invalid_checkpoint",
                            "Checkpoint image reference is invalid.",
                        )
                    relative = self.files.relative(value)
                    if relative.parts[0] not in {
                        "structures",
                        "structure_bindings",
                        "smiles",
                    } or relative.suffix.lower() not in {
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".webp",
                        ".tif",
                        ".tiff",
                    }:
                        raise WebError(
                            409,
                            "unsafe_checkpoint",
                            "Checkpoint asset is outside its approved stage.",
                        )
                    if str(relative) not in self.content:
                        self.put(str(relative), self.raw(str(relative)))
                else:
                    self.images(value, depth=depth + 1)
        elif isinstance(payload, list):
            for value in payload:
                self.images(value, depth=depth + 1)

    def verify(
        self, stage: str, spec: RunSpec, *, chunk_path: str | None = None
    ) -> VerifiedCheckpoint | None:
        from patent_sar_extractor.application.stage_cache import _stable_digest

        path, schema, version = ARTIFACTS[stage]
        if chunk_path is not None:
            if stage != "structures" or not re.fullmatch(
                r"structures/\.chunks/chunk_[0-9]{3,4}/metadata\.json", chunk_path
            ):
                raise WebError(
                    409,
                    "unsafe_checkpoint",
                    "Chunk checkpoint path is outside its approved stage.",
                )
            path = chunk_path
        payload = self.files.json(path)
        manifest = self.files.json(path + ".manifest.json")
        if not core.artifact_identity_matches(
            payload, schema, version
        ) or not core.artifact_identity_matches(
            manifest, core.STEP_MANIFEST_SCHEMA, core.STEP_MANIFEST_SCHEMA_VERSION
        ):
            return None
        if (
            type(payload["schema"]["version"]) is not int
            or type(manifest["schema"]["version"]) is not int
        ):
            return None
        collection = {
            "activity": "rows",
            "locate": "selected_pages",
            "structures": "structures",
            "bind": "final_bindings",
            "smiles": "records",
        }.get(stage)
        if collection:
            items = payload.get(collection)
            if not isinstance(items, list) or len(items) > MAX_RECORDS:
                return None
            if stage == "locate":
                if any(
                    type(item) is not int or not 0 <= item < 10000 for item in items
                ):
                    return None
            elif any(not isinstance(item, dict) for item in items):
                return None
        if stage == "classify":
            count = payload.get("page_count")
            if type(count) is not int or not 1 <= count <= 10000:
                return None
        if (
            stage in {"bind", "smiles"}
            and payload.get("execution_mode")
            != {
                "bind": "production_structure_led",
                "smiles": "production_decimer",
            }[stage]
        ):
            return None
        fp = manifest.get("fingerprint")
        if (
            not isinstance(fp, dict)
            or fp.get("step") != stage
            or fp.get("pdf_sha256") != spec.sha256
            or fp.get("product") != core.product_ref()
            or fp.get("pipeline_contract") != core.pipeline_contract_ref()
            or (stage != "classify" and fp.get("ruleset") != core.ruleset_ref())
            or not isinstance(fp.get("params"), dict)
            or fp.get("params_digest") != _stable_digest(fp["params"])
            or not isinstance(fp.get("dependency_sha256"), dict)
        ):
            return None
        for value in (
            payload.get("ocr_cache_path"),
            fp["params"].get("ocr_cache_path"),
        ):
            if value is not None and (
                not isinstance(value, str)
                or self.files.relative(value) != Path(OCR_PATH)
            ):
                raise WebError(
                    409,
                    "unsafe_checkpoint",
                    "Checkpoint OCR reference is outside its approved artifact.",
                )
        for dependency, expected in fp["dependency_sha256"].items():
            relative = str(self.files.relative(dependency))
            if relative not in DEPENDENCIES or relative not in self.content:
                return None
            if hashlib.sha256(self.raw(relative)).hexdigest() != expected:
                return None
        return VerifiedCheckpoint(stage, path, payload, manifest)

    def checkpoint(self, verified: VerifiedCheckpoint) -> None:
        from patent_sar_extractor.application.stage_cache import (
            _bindings_ocsr_digest,
            _stable_digest,
        )

        self.images(verified.payload)
        self.put(verified.path, checkpoint_json(self.relocate(verified.payload)))
        manifest = self.relocate(verified.manifest)
        fp = manifest["fingerprint"]
        fp["dependency_sha256"] = {
            str(self.target / self.files.relative(path)): self.content[
                str(self.files.relative(path))
            ]
            for path in verified.manifest["fingerprint"]["dependency_sha256"]
        }
        if verified.stage == "smiles":
            fp["params"]["bindings_ocsr_digest"] = _bindings_ocsr_digest(
                str(self.target / ARTIFACTS["bind"][0])
            )
        fp["params_digest"] = _stable_digest(fp["params"])
        self.put(verified.path + ".manifest.json", checkpoint_json(manifest))

    def observations(self) -> None:
        from patent_sar_extractor.core.ocsr.cache_snapshot import snapshot_observations

        relative = "smiles/smiles_cache.sqlite"
        try:
            content = self.raw(relative)
        except WebError as exc:
            if exc.code == "asset_unavailable":
                return
            raise
        try:
            snapshot = snapshot_observations(
                content, max_bytes=MAX_ARTIFACT_BYTES, max_records=MAX_RECORDS
            )
        except (ValueError, RecursionError, UnicodeError, sqlite3.Error) as exc:
            raise WebError(
                422, "invalid_checkpoint_cache", "Raw recognition cache is invalid."
            ) from exc
        self.put(relative, snapshot)


def checkpoint_json(payload: Any) -> bytes:
    # Use the canonical writer's serialization: the CLI hashes dependency bytes
    # and writes annotations again, so compact JSON would force needless misses.
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode()


def seed_checkpoints(
    old: RunSpec, target: Path, *, check_cancel: Callable[[], None] | None = None
) -> None:
    from patent_sar_extractor.core.page_ocr_cache import cache_matches_pdf

    copy = CheckpointCopy(Path(old.output_dir), target, check_cancel=check_cancel)
    cache = copy.files.json(OCR_PATH)
    # Raw page observations have their own compatibility contract. Applying
    # derived-artifact rules here rejects valid older OCR and needlessly forces
    # a full rescan; the core predicate still checks PDF SHA and observation ID.
    if isinstance(cache, dict) and cache_matches_pdf(cache, old.pdf_path):
        copy.put(OCR_PATH, checkpoint_json(copy.relocate(cache)))
    summary = read_summary(Path(old.output_dir))
    if not isinstance(summary, dict) or not core.artifact_identity_matches(
        summary, core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
    ):
        return
    for stage in ARTIFACTS:
        if summary["steps"].get(stage, {}).get("status") != "ok":
            break
        verified = copy.verify(stage, old)
        if verified is None:
            break
        copy.checkpoint(verified)
        if stage == "locate":
            regions = copy.files.json("structure_pages/crop_regions.json")
            if not isinstance(regions, dict):
                break
            copy.put(
                "structure_pages/crop_regions.json",
                checkpoint_json(copy.relocate(regions)),
            )
    if ARTIFACTS["bind"][0] in copy.content:
        # A failed SMILES stage can still contain useful raw observations. They
        # never become a stage checkpoint or acceptance report; the sole worker
        # rechecks their exact image/runtime identity and re-runs failed entries.
        copy.observations()
    if (
        ARTIFACTS["locate"][0] in copy.content
        and "structure_pages/crop_regions.json" in copy.content
    ):
        from .checkpoint_chunks import seed_structure_chunks

        seed_structure_chunks(copy, old)
