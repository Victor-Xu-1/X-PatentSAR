"""Occurrence-specific nonfinal declaration references, never page/ID skips."""

from collections import defaultdict

from .caption_role_semantics import catalog_title_role
from .cell_frame_proof import inside_box
from .source_cell_tokens import cell_text
from .source_observations import project_source_observation, source_observation_status
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
            if scope["role"] == "nonfinal" or (
                scope["role"] == "compound" and "caption_sources" in scope
            ):
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
    ):
        return None
    options = []
    for scope, source in index.get(page_no, []):
        body = scope["bbox"]
        category = (
            catalog_title_role(line["text"]) in {"compound", "nonfinal"}
            and catalog_title_role(line["text"]) == scope["role"]
            and not (observation and heading_members(observation))
            and any(
                source_observation_status(packet, packet["bbox"], packet["text"])
                == "qualified"
                and inside_box(box, packet["bbox"])
                and project_source_observation(packet, box)["text"] == line["text"]
                for packet in scope.get("caption_sources", [])
            )
        )
        in_body = (
            scope["role"] == "nonfinal"
            and observation is not None
            and observation["role"] == "compound_heading"
            and body[0] <= box[0] < box[2] <= body[2]
            and body[1] <= box[1] < box[3] <= scope["trusted_bottom"]
        )
        if not category and not in_body:
            continue
        tokens = window_source_tokens(
            source["page_context"], box, native=line["source"] == "native"
        )
        text = cell_text(tokens, box)
        if (
            category
            and text == line["text"]
            or in_body
            and section_heading(text) == observation
        ):
            options.append((scope, source, category))
    if len(options) != 1:
        return None
    scope, source, category = options[0]
    return {
        "role": REFERENCE_ROLE,
        "status": "observed_original_catalogue_title_reference"
        if category
        else "observed_nonfinal_source_reference",
        "source_region": scope["source_region"],
        "original_pdf_sha256": source["original_pdf_sha256"],
        "page_no": page_no,
        "bbox": list(box),
        "line_text": line["text"],
        "line_source": line["source"],
        "geometry_space": "rendered",
        "identifiers": [] if category else heading_members(observation),
    }
