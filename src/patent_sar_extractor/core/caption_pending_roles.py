"""Keep rejected original catalogue occurrences distinct from synthesis titles.

An occurrence role never supplies an identifier, molecule or successful binding.
The original rejected proposal remains mandatory and independently unresolved.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .caption_label_roles import PENDING_ROLE, owns_label_locator
from .caption_role_proof import caption_role_status
from .source_cell_claims import cell_source_status
from .source_evidence_identity import proof_id
from .source_role_observations import validate_role_catalog
from .source_section_roles import section_heading


def _locator_text(text):
    # A raw-locator alias key, never a normalized scientific identifier.
    return "".join(text.split()).casefold()


def pending_caption_index(catalog, original_pdf_sha256):
    """Index proved physical caption roles, not unqualified proposed label IDs."""
    validate_role_catalog(catalog, original_pdf_sha256=original_pdf_sha256)
    index = defaultdict(list)
    for key, diagnostic in catalog.items():
        if diagnostic.get("kind") != "binding_proposal":
            continue
        proposal = diagnostic["proposal"]
        page, box = proposal.get("page"), proposal.get("bbox")
        role, readings = proposal.get("caption_role"), proposal.get("observations")
        if (
            type(page) is not int
            or page != diagnostic["page_no"]
            or proposal.get("direction") not in {"above", "below"}
            or not isinstance(readings, list)
            or caption_role_status(role, page, box) != "compound"
        ):
            continue
        role_id = proof_id(
            {"status": "observed_original_caption_role", "caption_role": role}
        )
        # Only the original cell carrier nominates this occurrence. A later
        # model string cannot invent a page token or acquire a native role.
        for reading in readings:
            if (
                not isinstance(reading, dict)
                or reading.get("method") not in {"native_cell", "page_ocr_cell"}
                or reading.get("bbox") != list(box)
                or cell_source_status(reading) in {"invalid", "legacy"}
                or not isinstance(reading.get("text"), str)
            ):
                continue
            source = "native" if reading["method"] == "native_cell" else "page_ocr"
            index[(page, source, _locator_text(reading["text"]))].append(
                {
                    "bbox": list(box),
                    "role_id": role_id,
                    "source_diagnostic": key,
                }
            )
    return dict(index)


def pending_caption_reference(line, page_no, index, original_pdf_sha256):
    """Alias exactly one original unresolved cell without adopting its number."""
    box = line.get("bbox")
    nomination = section_heading(line.get("text"))
    if (
        type(page_no) is not int
        or line.get("source") not in {"native", "page_ocr"}
        or line.get("geometry_space") != "rendered"
        or not isinstance(box, (list, tuple))
        or len(box) != 4
        or any(type(v) not in {int, float} or not math.isfinite(v) for v in box)
        or not box[0] < box[2]
        or not box[1] < box[3]
        or not nomination
        or nomination["role"] != "compound_heading"
    ):
        return None

    options = defaultdict(set)
    for source in index.get((page_no, line["source"], _locator_text(line["text"])), []):
        if owns_label_locator(box, source["bbox"]):
            options[(tuple(source["bbox"]), source["role_id"])].add(
                source["source_diagnostic"]
            )
    if len(options) != 1:
        return None
    return {
        "role": PENDING_ROLE,
        "status": "unresolved",
        "page_no": page_no,
        "bbox": list(box),
        "line_text": line["text"],
        "line_source": line["source"],
        "geometry_space": "rendered",
        "original_pdf_sha256": original_pdf_sha256,
        "source_diagnostics": sorted(next(iter(options.values()))),
    }


def validate_pending_caption_references(sections, scope, catalog):
    references = [s for s in sections if s.get("role") == PENDING_ROLE]
    if not references:
        return
    origin = scope["original_pdf_sha256"]
    if not origin:
        raise ValueError("Unresolved original caption reference has no source")
    index = pending_caption_index(catalog, origin)
    for reference in references:
        expected = pending_caption_reference(
            {
                "text": reference.get("line_text"),
                "source": reference.get("line_source"),
                "geometry_space": reference.get("geometry_space"),
                "bbox": reference.get("bbox"),
            },
            reference.get("page_no"),
            index,
            origin,
        )
        if expected is None or expected != reference:
            raise ValueError("Unproved unresolved original caption occurrence")
