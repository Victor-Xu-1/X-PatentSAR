"""Bounded activity-led adaptation of real core artifacts to Web DTOs."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from patent_sar_extractor.core.pipeline_rules import (
    _label_key,
    annotate_binding_accuracy,
)

from .acceptance import ARTIFACTS, authority, current
from .errors import WebError
from .files import MAX_RECORDS, SafeFiles, records
from .models import Activity, Compound, Confidence, ConfidenceLevel, Source, Summary
from .molecule_drawing import drawing_url
from .recognition import recognition_status


def text(value: object, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise WebError(
            422, "invalid_artifact", "Artifact contains invalid scalar metadata."
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise WebError(
            422, "invalid_artifact", "Artifact contains a non-finite number."
        )
    return str(value)[:limit]


def page_number(value: object) -> int | None:
    if value in (None, 0, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise WebError(422, "invalid_artifact", "Artifact page number is invalid.")
    try:
        page = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise WebError(
            422, "invalid_artifact", "Artifact page number is invalid."
        ) from exc
    if not 1 <= page <= 20000:
        raise WebError(
            422, "invalid_artifact", "Artifact page number is outside bounds."
        )
    return page


def box(binding: dict[str, Any], structure: dict[str, Any]) -> list[float] | None:
    value = structure.get("bbox_pdf")
    if value is None and all(
        k in binding for k in ("struct_x0", "struct_y0", "struct_x1", "struct_y1")
    ):
        value = [
            binding[k] for k in ("struct_x0", "struct_y0", "struct_x1", "struct_y1")
        ]
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise WebError(422, "invalid_geometry", "Artifact geometry is invalid.")
    try:
        bounds = [float(x) for x in value]
    except (TypeError, ValueError, OverflowError) as exc:
        raise WebError(
            422, "invalid_geometry", "Artifact geometry is invalid."
        ) from exc
    if (
        not all(math.isfinite(x) and abs(x) <= 100000 for x in bounds)
        or bounds[2] <= bounds[0]
        or bounds[3] <= bounds[1]
    ):
        raise WebError(
            422, "invalid_geometry", "Artifact geometry is non-finite or inverted."
        )
    return bounds


def _index(
    items: list[dict[str, Any]], keys: tuple[str, ...]
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        label = next((item.get(k) for k in keys if item.get(k)), "")
        key = _label_key(text(label) or "")
        if key:
            index.setdefault(key, []).append(item)
    return index


_ActivityContext = tuple[int | None, str | None, str | None]


def _provenance_error() -> WebError:
    return WebError(
        422,
        "invalid_artifact",
        "Activity provenance contains invalid or over-limit data.",
    )


def _provenance_text(value: object, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise _provenance_error()
    return value


def _provenance_cell(cell: object) -> tuple[str, str | None]:
    if not isinstance(cell, dict):
        raise _provenance_error()
    name = _provenance_text(cell.get("field"), limit=300)
    value = text(cell.get("value"), limit=1001)
    if not name or (value is not None and len(value) > 1000):
        raise _provenance_error()
    bounds = cell.get("bbox")
    if bounds is not None and (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or not all(
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            and 0 <= x <= 100000
            and math.isfinite(x)
            for x in bounds
        )
        or bounds[2] <= bounds[0]
        or bounds[3] <= bounds[1]
    ):
        raise _provenance_error()
    observations = cell.get("observations", [])
    if not isinstance(observations, list) or len(observations) > 20:
        raise _provenance_error()
    for observation in observations:
        if not isinstance(observation, dict) or len(observation) > 16:
            raise _provenance_error()
        _provenance_text(observation.get("method"), limit=300)
        _provenance_text(observation.get("text"), limit=10000)
        confidence = observation.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise _provenance_error()
    return name, value


def _activity_sources(
    row: dict[str, Any], fallback: _ActivityContext, *, page_count: int
) -> dict[tuple[str, str | None], list[_ActivityContext]]:
    sources = row.get("activity_sources")
    if sources is None:
        return {}
    if not isinstance(sources, list) or len(sources) > 500:
        raise _provenance_error()
    index: dict[tuple[str, str | None], dict[_ActivityContext, None]] = {}
    cell_count = 0
    for source in sources:
        if not isinstance(source, dict) or len(source) > 32:
            raise _provenance_error()
        raw_page = source.get("page_no", fallback[0])
        if raw_page is not None and (
            not isinstance(raw_page, (int, str))
            or isinstance(raw_page, bool)
            or raw_page == 0
        ):
            raise _provenance_error()
        page = page_number(raw_page)
        if page and page_count and page > page_count:
            raise _provenance_error()
        context = (
            page,
            _provenance_text(source["target"], limit=300)
            if "target" in source
            else fallback[1],
            _provenance_text(source["assay"]) if "assay" in source else fallback[2],
        )
        _provenance_text(source.get("cell_line"), limit=300)
        _provenance_text(source.get("table_id"), limit=300)
        for field in ("row", "pair"):
            number = source.get(field)
            if number is not None and (
                not isinstance(number, int)
                or isinstance(number, bool)
                or not 0 <= number <= 1000000
            ):
                raise _provenance_error()
        cells = source.get("cells", [])
        if not isinstance(cells, list) or len(cells) > 500:
            raise _provenance_error()
        cell_count += len(cells)
        if cell_count > 2000:
            raise _provenance_error()
        for cell in cells:
            # OCR attempts are observations of one cell, not new measurements.
            # Preserve distinct observed assay contexts, deduplicating repeats.
            index.setdefault(_provenance_cell(cell), {})[context] = None
    return {key: list(contexts) for key, contexts in index.items()}


def _activities(row: dict[str, Any], *, page_count: int = 0) -> list[Activity]:
    fallback = (
        page_number(row.get("page_no")),
        text(row.get("target")),
        text(row.get("assay")),
    )
    if fallback[0] and page_count and fallback[0] > page_count:
        raise _provenance_error()
    sources = _activity_sources(row, fallback, page_count=page_count)
    output = []
    for field in ("activity_values", "cell_line_data"):
        values = row.get(field) or {}
        if not isinstance(values, dict) or len(values) > 500:
            raise WebError(
                422,
                "invalid_artifact",
                "Activity metric collection is invalid or over limit.",
            )
        for name, value in values.items():
            if not isinstance(name, str) or len(name) > 300:
                raise WebError(
                    422, "invalid_artifact", "Activity metric name is invalid."
                )
            unit_match = re.search(r"\(([^()]+)\)\s*$", name)
            # Match exact field/value before presentation truncation; equal
            # grades in different tables must not borrow each other's sources.
            contexts = sources.get((name, text(value, limit=1001)), [fallback])
            for page, target, assay in contexts:
                output.append(
                    Activity(
                        name=name,
                        value=text(value),
                        unit=unit_match.group(1) if unit_match else None,
                        target=target,
                        assay=assay,
                        page=page,
                    )
                )
                if len(output) > 2000:
                    raise WebError(
                        422,
                        "artifact_limit",
                        "A compound has too many activity measurements.",
                    )
    return output


@dataclass
class ArtifactView:
    root: Path
    payloads: dict[str, Any]
    ocr: dict[str, Any]
    expected_sha256: str | None
    page_count: int

    @classmethod
    def read(cls, root: Path) -> ArtifactView:
        files = SafeFiles(root)
        payloads = {name: files.json(path) for name, (path, _, _) in ARTIFACTS.items()}
        for name, payload in payloads.items():
            if (
                payload is not None
                and not isinstance(payload, dict)
                and not (name == "smiles" and isinstance(payload, list))
            ):
                raise WebError(
                    422, "invalid_artifact", "Run artifact must be a supported object."
                )
        ocr = files.json("page_classification/page_ocr_cache.json") or {}
        if not isinstance(ocr, dict):
            raise WebError(422, "invalid_artifact", "OCR artifact is not an object.")
        metadata = ocr.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise WebError(422, "invalid_artifact", "OCR metadata is not an object.")
        hashes = set()
        source_hash = metadata.get("pdf_sha256")
        if source_hash:
            hashes.add(source_hash)
        for name in ("classification", "activity", "bindings"):
            manifest = files.json(ARTIFACTS[name][0] + ".manifest.json")
            if isinstance(manifest, dict) and isinstance(
                manifest.get("fingerprint"), dict
            ):
                fingerprint_hash = manifest["fingerprint"].get("pdf_sha256")
                if fingerprint_hash:
                    hashes.add(fingerprint_hash)
        if (
            any(
                not isinstance(h, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", h)
                for h in hashes
            )
            or len(hashes) > 1
        ):
            raise WebError(
                422,
                "source_identity",
                "Run artifacts have invalid or conflicting source fingerprints.",
            )
        count = (
            metadata.get("page_count")
            or (payloads.get("classification") or {}).get("page_count")
            or 0
        )
        count = page_number(count) or 0
        return cls(
            root, payloads, ocr, next(iter(hashes)).lower() if hashes else None, count
        )

    def snapshot(
        self, project_id: str, *, pdf_sha256: str | None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        from .stages import completed_stage_payloads

        p = completed_stage_payloads(self.payloads)
        files = SafeFiles(self.root)
        verified = bool(pdf_sha256 and pdf_sha256 == self.expected_sha256)
        marker = files.json("STRICT_ACCEPTANCE_FAILED.json")
        accepted, historical = authority(p, pdf_verified=verified, marker=marker)
        steps = (p.get("summary") or {}).get("steps", {})
        structure_step = steps.get("structures", {}) if isinstance(steps, dict) else {}
        structure_failed = (
            isinstance(structure_step, dict)
            and structure_step.get("status") == "failed"
        ) or (isinstance(marker, dict) and marker.get("stage") == "structures")
        activity = p.get("activity") or {}
        rows = records(activity, "rows")
        active = activity.get("active_cpds")
        if active is None:
            active = list(
                dict.fromkeys(
                    text(row.get("cpd"), limit=200) for row in rows if row.get("cpd")
                )
            )
        if not isinstance(active, list) or len(active) > MAX_RECORDS:
            raise WebError(
                422,
                "artifact_limit",
                "Activity compound collection exceeds its limits.",
            )
        if any(
            not isinstance(x, str)
            or not x
            or len(x) > 200
            or any(ord(c) < 32 for c in x)
            for x in active
        ):
            raise WebError(
                422, "invalid_artifact", "Activity compound identifiers are invalid."
            )
        if len(set(active)) != len(active):
            raise WebError(
                422, "invalid_artifact", "Activity compound identifiers are not unique."
            )
        binding_payload = p.get("bindings") or {}
        binding_key = (
            "final_bindings" if "final_bindings" in binding_payload else "bindings"
        )
        bindings = _index(
            records(binding_payload, binding_key), ("compound_id", "cpd", "cpd_id")
        )
        smiles_payload = p.get("smiles")
        if isinstance(smiles_payload, list):
            if len(smiles_payload) > MAX_RECORDS or any(
                not isinstance(x, dict) for x in smiles_payload
            ):
                raise WebError(
                    422, "artifact_limit", "Historical SMILES collection is invalid."
                )
            smiles_rows = smiles_payload
        else:
            smiles_rows = records(smiles_payload, "records")
        smiles = _index(smiles_rows, ("cpd_id", "cpd", "compound_id"))
        structure_rows = records(p.get("structures"), "structures")
        structures = {text(s.get("structure_id")): s for s in structure_rows}
        activity_index = _index(rows, ("cpd",))
        compounds = []
        confirmed = 0
        matched = 0
        metric_names: set[str] = set()
        crop_revision = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        targets: set[str] = set()
        measurement_count = 0
        for compound_id in active:
            key = _label_key(compound_id)
            candidates = bindings.get(key, [])
            binding = candidates[0] if len(candidates) == 1 else {}
            flags = []
            if len(candidates) > 1:
                flags.append("ambiguous_binding")
            structure_id = text(binding.get("structure_id"), limit=200)
            structure = structures.get(structure_id) or {}
            geometry = box(binding, structure)
            image_path = text(
                binding.get("image_path") or structure.get("image_path"), limit=4096
            )
            if image_path:
                try:
                    with files.open(image_path, max_bytes=16 * 1024 * 1024):
                        pass
                except WebError:
                    flags.append("image_unavailable")
                    image_path = None
            has_crop = bool(image_path or (verified and geometry))
            if not has_crop and "image_unavailable" not in flags:
                if binding or structure:
                    flags.append("image_unavailable")
                elif not historical and structure_failed:
                    flags.append("structure_generation_failed")
                elif not historical and p.get("structures") is None:
                    flags.append("structure_not_generated")
            if historical:
                confidence = Confidence(
                    level="review",
                    reason="Historical artifact identity; not current confirmation.",
                )
                flags.append("historical_identity")
            elif (
                binding
                and verified
                and current(p.get("bindings"), "bindings")
                and binding_payload.get("execution_mode") == "production_activity_led"
            ):
                try:
                    evidence = annotate_binding_accuracy(binding)
                except (TypeError, ValueError, OverflowError, AttributeError) as exc:
                    raise WebError(
                        422,
                        "invalid_evidence",
                        "Binding evidence contains invalid values.",
                    ) from exc
                high = evidence.get(
                    "accuracy_status"
                ) == "confirmed" and not evidence.get("fail_closed")
                level: ConfidenceLevel = (
                    "high"
                    if high
                    else "medium"
                    if evidence.get("evidence_tier") == "medium"
                    else "review"
                )
                confidence = Confidence(
                    level=level,
                    reason="Current core binding evidence."
                    if high
                    else "Core binding requires review.",
                )
            else:
                confidence = Confidence(
                    reason="No unique current core binding evidence."
                )
            activities = [
                entry
                for row in activity_index.get(key, [])
                for entry in _activities(row, page_count=self.page_count)
            ]
            if len(activities) > 2000:
                raise WebError(
                    422,
                    "artifact_limit",
                    "A compound has too many activity measurements.",
                )
            measurement_count += len(activities)
            if measurement_count > 100000:
                raise WebError(
                    422,
                    "artifact_limit",
                    "Run has too many activity measurements for the local workspace.",
                )
            metric_names.update(a.name for a in activities)
            targets.update(a.target for a in activities if a.target)
            if len(metric_names) > 1000 or len(targets) > 1000:
                raise WebError(
                    422,
                    "artifact_limit",
                    "Run metric or target vocabulary exceeds its limit.",
                )
            if not binding:
                flags.append("structure_unmatched")
            else:
                matched += 1
            confirmed += int(confidence.level == "high")
            smile_records = smiles.get(key, [])
            smile = smile_records[0] if len(smile_records) == 1 else {}
            if len(smile_records) > 1:
                flags.append("ambiguous_smiles")
            source_page = page_number(
                binding.get("page_no") or structure.get("page_no")
            )
            if source_page is None and activities:
                source_page = activities[0].page
            dto = Compound(
                id=compound_id,
                display_id=compound_id,
                structure_id=structure_id,
                structure_image_url=(
                    f"/api/v1/projects/{project_id}/structures/{quote(compound_id, safe='')}/image?revision={crop_revision}"
                    if has_crop
                    else None
                ),
                smiles=text(
                    smile.get("smiles") or smile.get("canonical_smiles"), limit=10000
                ),
                recognition=recognition_status(
                    smile, current=current(p.get("smiles"), "smiles")
                ),
                redraw_image_url=(
                    drawing_url(
                        project_id,
                        compound_id,
                        text(
                            smile.get("smiles") or smile.get("canonical_smiles"),
                            limit=10000,
                        ),
                    )
                    if smile.get("smiles") or smile.get("canonical_smiles")
                    else None
                ),
                activities=activities,
                source=Source(
                    page=source_page,
                    paragraph=text(binding.get("paragraph")),
                    bbox=geometry,
                    source_label=text(
                        binding.get("authoritative_table_source_label")
                        or binding.get("authoritative_table_visible_label")
                        or binding.get("visible_label")
                    ),
                    correction_reason=text(
                        binding.get("authoritative_table_correction_reason")
                        or binding.get("correction_reason")
                    ),
                ),
                confidence=confidence,
                flags=flags,
            )
            # Core segmentation divides rotated pixmap pixels by its scale.
            # Its bbox_pdf is already in rendered-page points; do not rotate twice.
            compounds.append(
                {
                    "dto": dto.model_dump(),
                    "image_path": image_path,
                    "geometry_space": "rendered"
                    if structure.get("bbox_pdf")
                    else "unrotated",
                }
            )
        summary = Summary(
            structures=len(structure_rows),
            activity_rows=len(rows),
            matched_structures=matched,
            confirmed=confirmed,
            needs_review=len(compounds) - confirmed,
        )
        snapshot = {
            "is_historical": historical,
            "acceptance": accepted.model_dump(),
            "summary": summary.model_dump(),
            "metrics": sorted(metric_names),
            "targets": sorted(targets),
        }
        return snapshot, compounds
