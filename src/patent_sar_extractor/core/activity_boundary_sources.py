"""Current-page boundary owners in the existing original activity inventory."""

from .activity_parallel_context import validate_context_boundary
from .source_evidence_identity import proof_id


def layout_boundary_sources(layout, page_no):
    """Every borrowed header keeps its local boundary, not just the parent."""
    origin = layout.get("header_origin")
    if layout.get("data_start") == 0 and isinstance(origin, dict):
        required = (
            "continuation_context"
            if origin.get("page_no", page_no) < page_no
            else "parallel_context"
        )
        if layout.get(required) is None:
            raise ValueError("Missing original borrowed-header boundary")
    for name in ("parallel_context", "continuation_context"):
        scope = layout.get(name)
        if scope is None:
            continue
        checked = validate_context_boundary(
            layout, scope, layout.get("boundary_prefix", layout["prefix"])
        )
        if scope["version"] != 2:
            raise ValueError("Historical boundary lacks current original replay")
        yield checked[0], checked[1]


def original_context_boundaries(payload):
    records = (payload.get("coverage") or {}).get("regions", [])
    if not isinstance(records, list) or len(records) > 25000:
        raise ValueError("Original context boundaries exceed their inventory")
    seen = set()
    for record in records:
        layout = record.get("layout")
        if layout is None:
            continue
        page_no = record.get("page_no")
        if type(page_no) is not int or not 1 <= page_no <= 20000:
            raise ValueError("Missing original boundary page ownership")
        for scope, bounds in layout_boundary_sources(layout, page_no):
            identity = (
                page_no,
                proof_id({"status": "activity_context_boundary", "source": scope}),
            )
            if identity in seen:
                continue  # Share full-frame work, never distinct local claim owners.
            seen.add(identity)
            yield page_no, scope, bounds
