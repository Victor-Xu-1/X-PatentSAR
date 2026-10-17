"""Occurrence-specific nonfinal declaration references, never page/ID skips."""

from collections import defaultdict

from .source_cell_tokens import cell_text
from .source_section_roles import heading_members, section_heading
from .source_window_chunks import window_source_tokens
from .structure_declaration_scopes import PAGE_ROLE, REFERENCE_ROLE, declaration_scopes


def declaration_role_index(sections, original_pdf_sha256=None):
    index = defaultdict(list)
    for section in sections:
        if section.get("role") != PAGE_ROLE:
            continue
        source = section["source"]
        if (
            original_pdf_sha256 is not None
            and source.get("original_pdf_sha256") != original_pdf_sha256
        ):
            raise ValueError("Foreign original nonfinal declaration source")
        for scope in declaration_scopes(source):
            if scope["role"] == "nonfinal":
                index[scope["page_no"]].append((scope, source))
    return index


def declaration_label_reference(line, page_no, index):
    box = line.get("bbox")
    observation = section_heading(line.get("text"))
    if (
        line.get("source") not in {"native", "page_ocr"}
        or line.get("geometry_space") != "rendered"
        or not isinstance(box, (list, tuple))
        or len(box) != 4
        or any(type(v) not in (int, float) for v in box)
        or not observation
        or observation["role"] != "compound_heading"
    ):
        return None
    options = []
    for scope, source in index.get(page_no, []):
        body = scope["bbox"]
        if not (
            body[0] <= box[0] < box[2] <= body[2]
            and body[1] <= box[1] < box[3] <= scope["trusted_bottom"]
        ):
            continue
        tokens = window_source_tokens(
            source["page_context"], box, native=line["source"] == "native"
        )
        original = section_heading(cell_text(tokens, box))
        if original == observation:
            options.append((scope, source))
    if len(options) != 1:
        return None
    scope, source = options[0]
    return {
        "role": REFERENCE_ROLE,
        "status": "observed_nonfinal_source_reference",
        "source_region": scope["source_region"],
        "original_pdf_sha256": source["original_pdf_sha256"],
        "page_no": page_no,
        "bbox": list(box),
        "line_text": line["text"],
        "line_source": line["source"],
        "geometry_space": "rendered",
        "identifiers": heading_members(observation),
    }
