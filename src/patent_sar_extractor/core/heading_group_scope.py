"""Plural headings reference proved local depictions, never assign their order."""

from collections import defaultdict

from .activity_context_geometry import valid_box
from .cell_frame_proof import inside_box
from .compound_caption import prefixed_label
from .heading_source_proof import proved_heading_declaration
from .printed_identifiers import identifier_key
from .source_binding_proof import annotate_source_binding
from .source_body_context import box_inside_drawing
from .source_cell_tokens import cell_lines, cell_text, cell_tokens
from .source_section_roles import (
    heading_members,
    procedure_heading_boundary,
    section_heading,
)
from .source_table_markers import TABLE_CAPTION_START
from .source_window_chunks import (
    observe_source_window,
    validate_source_window,
    window_source_tokens,
)


def observe_group_context(page, tokens, original_sha):
    """Retain the existing complete page tokens; never start a page OCR here."""
    size = [page.rect.width, page.rect.height]
    return {
        "version": 1,
        "original_pdf_sha256": original_sha,
        "page_no": page.number + 1,
        "page_size": size,
        "source_chunks": observe_source_window(tokens, [0, 0, *size]),
    }


def _context(section, proof):
    context = section.get("group_context")
    if context is None:
        return None
    if not isinstance(context, dict) or (
        set(context)
        != {"version", "original_pdf_sha256", "page_no", "page_size", "source_chunks"}
        or type(context["version"]) is not int
        or context["version"] != 1
        or any(
            context[name] != proof[name]
            for name in ("original_pdf_sha256", "page_no", "page_size")
        )
        or type(context["page_no"]) is not int
        or not valid_box([0, 0, *context["page_size"]])
    ):
        raise ValueError("Malformed original plural-heading context")
    validate_source_window(context["source_chunks"], [0, 0, *context["page_size"]])
    return context


def _sources(entries, original_sha, page_no):
    sources, count = [], 0
    if not isinstance(entries, (list, tuple)) or len(entries) > 25000:
        raise ValueError("Original heading sources exceed their bound")
    for entry in entries:
        if not isinstance(entry, dict):
            raise TypeError("Malformed original heading source")
        additional = entry.get("additional_sources", [])
        if not isinstance(additional, (list, tuple)) or len(additional) > 1000:
            raise ValueError("Malformed original heading reprint sources")
        for source in (entry, *additional):
            count += 1
            if count > 25000 or not isinstance(source, dict):
                raise ValueError("Original heading source anchors exceed their bound")
            if (
                source.get("page_no") != page_no
                or source.get("source_pdf_sha256") != original_sha
            ):
                continue
            checked = annotate_source_binding(source)
            if checked.get("accuracy_status") != "confirmed" or checked.get(
                "fail_closed"
            ):
                continue
            field = {
                "original_caption_cell": "exact_caption_evidence",
                "numbered_structure_table_cell": "numbered_table_cell_evidence",
            }.get(checked.get("binding_rule"))
            if field is None:
                continue
            packet = checked[field]
            if packet["page_no"] != page_no:
                continue
            label_box = (
                packet["bbox"]
                if field == "exact_caption_evidence"
                else packet["label_bbox"]
            )
            sources.append(
                {
                    "label": identifier_key(checked.get("cpd"), wrapped=True),
                    "id": str(checked["structure_id"]),
                    "bbox": [
                        checked["struct_" + name] for name in ("x0", "y0", "x1", "y1")
                    ],
                    "label_bbox": list(label_box),
                }
            )
    return sources


def _caption_tokens(tokens, sources, members):
    protected = set()
    for source in sources:
        if source["label"] not in members:
            continue
        box = source["label_bbox"]
        selected = cell_tokens(tokens, box)
        if not selected:
            continue  # No native lane is not a vote against original raster.
        text = cell_text(selected, box)
        label = prefixed_label(text) or identifier_key(text, terminal_period=True)
        if label != source["label"] or not all(
            inside_box(part["bbox"], box)
            and part["confidence_available"]
            and part["confidence_valid"]
            and part["confidence"] >= 0.85
            for part in selected
        ):
            return None  # Unknown, weak or conflicting originals remain explicit.
        protected.update(id(part) for part in selected)
    return protected


def _local_source(context, proof, source, sources, members):
    size, chunks = context["page_size"], context["source_chunks"]
    heading = proof["nomination"]["bbox"]
    top, bottom = heading[3], max(source["bbox"][3], source["label_bbox"][3])
    if min(source["bbox"][1], source["label_bbox"][1]) < top:
        return False
    window = [0, top, size[0], bottom]
    if (
        not valid_box(window)
        or not inside_box(source["bbox"], [0, 0, *size])
        or not inside_box(source["label_bbox"], [0, 0, *size])
    ):
        return False
    for native in (False, True):
        tokens = window_source_tokens(chunks, [0, 0, *size], native=native)
        # A simultaneous independent column title is not part of this source.
        # Without an original column boundary no whole-page association is made.
        if any(
            min(part["bbox"][3], heading[3]) > max(part["bbox"][1], heading[1])
            and not inside_box(part["bbox"], proof["bbox"])
            for part in tokens
        ):
            return False
        protected = _caption_tokens(cell_tokens(tokens, window), sources, members)
        if protected is None:
            return False
        remaining = [
            part
            for part in cell_tokens(tokens, window)
            if id(part) not in protected
            and not box_inside_drawing(part["bbox"], sources)
        ]
        if any(
            not inside_box(part["bbox"], window)
            or not part["confidence_available"]
            or not part["confidence_valid"]
            or part["confidence"] < 0.85
            for part in remaining
        ):
            return False
        for line in cell_lines(remaining, window):
            text = cell_text(line, window)
            if (
                procedure_heading_boundary(text)
                or section_heading(text)
                or TABLE_CAPTION_START.match(text)
            ):
                return False
    return True


def group_heading_members(section, entries, original_sha):
    """Only independent current anchors below this exact original declaration."""
    proof = section.get("heading_observation")
    declaration = proved_heading_declaration(proof)
    members = heading_members(declaration)
    if not declaration or declaration["role"] != "compound_heading" or len(members) < 2:
        if "group_context" in section:
            raise ValueError("Original group context has no plural declaration")
        return set()
    context = _context(section, proof)
    if context is None or proof["original_pdf_sha256"] != original_sha:
        return set()
    sources = _sources(entries, original_sha, proof["page_no"])
    candidates = defaultdict(set)
    for source in sources:
        if source["label"] in members and _local_source(
            context, proof, source, sources, members
        ):
            candidates[source["label"]].add((source["id"], tuple(source["label_bbox"])))
    return {label for label, anchors in candidates.items() if len(anchors) == 1}
