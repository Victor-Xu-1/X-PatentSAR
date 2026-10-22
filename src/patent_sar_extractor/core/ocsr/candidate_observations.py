"""One source plan conserves detected images without inventing compound labels."""

from collections import defaultdict
from dataclasses import dataclass, replace

from patent_sar_extractor.contracts import MAX_RECOGNITION_SOURCES

from ..activity_context_geometry import valid_box
from .candidate_inventory import (
    asset_digest,
    candidate_descriptor,
    inventory_digest,
    original_candidate_inventory,
)
from .candidate_scope import (
    RESULT_FIELDS,
    SOURCE_ROLES,
    validate_candidate_scope,
    validate_inventory_records,
)
from .recognition_inputs import RecognitionPlan
from .recognition_source_paths import resolve_image_paths, resolve_ocsr_image_path


@dataclass(frozen=True)
class CandidatePlan:
    proven: RecognitionPlan
    candidates: list[dict]
    inventory: dict

    @property
    def work_items(self):
        return [*self.proven.work_items, *self.candidates]


def _source_identity(row, original_sha, read_digest):
    box = row.get("bbox_pdf")
    if box is None:
        box = [row.get("struct_" + axis) for axis in ("x0", "y0", "x1", "y1")]
    path = resolve_ocsr_image_path(row)
    if (
        not path
        or not valid_box(box)
        or type(row.get("page_no")) is not int
        or row.get("source_pdf_sha256") != original_sha
    ):
        return None
    digest = read_digest(path)
    if digest is None:
        return None
    return (
        row.get("source_structure_id") or row.get("structure_id"),
        row["page_no"],
        tuple(box),
        digest,
    )


def build_candidate_plan(
    metadata,
    manifest,
    proven,
    *,
    original_pdf_sha256,
    metadata_dir,
    binding_dir,
    read_digest=asset_digest,
):
    """Reuse only the same raw asset/page/geometry; all other inputs stay unassigned."""
    inventory, entries = original_candidate_inventory(
        metadata, manifest, original_pdf_sha256, metadata_dir, read_digest=read_digest
    )
    count, groups, positions = 0, [], defaultdict(list)
    for role, rows in zip(
        SOURCE_ROLES, (proven.formal, proven.supplemental, proven.reprints), strict=True
    ):
        resolved = resolve_image_paths(rows, str(binding_dir), attach_geometry=False)
        groups.append(resolved)
        count += len(resolved)
        for index, row in enumerate(resolved):
            if row.get("source_pdf_sha256") != original_pdf_sha256:
                raise ValueError(
                    "A proved recognition source belongs to another original document"
                )
            identity = _source_identity(row, original_pdf_sha256, read_digest)
            if identity is not None:
                positions[identity].append({"role": role, "index": index})
    candidates, observed = [], []
    for entry in entries:
        identity = (
            entry["structure_id"],
            entry["page_no"],
            tuple(entry["bbox_pdf"]),
            entry["image_sha256"],
        )
        reusable = positions.get(identity, ())
        if len(reusable) == 1:
            reference = reusable[0]
        else:
            reference = {"role": "candidate", "index": len(candidates)}
            source = candidate_descriptor(entry, original_pdf_sha256)
            candidates.append(
                {
                    "cpd": "",
                    "bind_status": "candidate",
                    "structure_id": entry["structure_id"],
                    "page_no": entry["page_no"],
                    "bbox_pdf": list(entry["bbox_pdf"]),
                    "image_path": entry["image_path"],
                    "source_image_path": entry["image_path"],
                    "candidate_source": source,
                    "candidate_source_id": inventory_digest(source),
                }
            )
        observed.append({**entry, "observation": reference})
    if count + len(candidates) > MAX_RECOGNITION_SOURCES:
        raise ValueError("Complete recognition source plan exceeds its bound")
    inventory["entries"] = observed
    inventory["identity"] = inventory_digest(inventory)
    validate_candidate_scope(inventory)
    return CandidatePlan(
        replace(proven, formal=groups[0], supplemental=groups[1], reprints=groups[2]),
        candidates,
        inventory,
    )


def validate_candidate_observations(plan, payload, *, read_digest=asset_digest):
    from .recognition_inputs import ordered_source_results

    actual = payload.get("candidate_inventory")
    validate_candidate_scope(actual)
    if (
        not isinstance(actual, dict)
        or actual != plan.inventory
        or actual.get("identity")
        != inventory_digest(
            {key: value for key, value in actual.items() if key != "identity"}
        )
    ):
        raise ValueError("Detected-image observation inventory was omitted or changed")
    inputs = (
        plan.proven.formal,
        plan.proven.supplemental,
        plan.proven.reprints,
        plan.candidates,
    )
    groups = {}
    for role, field, rows in zip(
        (*SOURCE_ROLES, "candidate"), RESULT_FIELDS, inputs, strict=True
    ):
        records = payload.get(field)
        if not isinstance(records, list) or not ordered_source_results(rows, records):
            raise ValueError(
                "Detected-image observations are missing, reordered or misassigned"
            )
        groups[role] = records
    validate_inventory_records(actual, payload)
    for entry in actual["entries"]:
        reference = entry["observation"]
        row = groups[reference["role"]][reference["index"]]
        if read_digest(entry["image_path"]) != entry["image_sha256"]:
            raise ValueError(
                "Detected-image source observation has changed or is unprocessed"
            )
        original = row.get("ocsr_original_input")
        if (
            not isinstance(original, str)
            or not original
            or read_digest(original) != entry["image_sha256"]
        ):
            raise ValueError("Detected-image result has another original input")
