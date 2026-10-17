"""Unruled columns join the existing original-cell owner and artifact writer."""

from collections import defaultdict
from dataclasses import dataclass

from .activity_header_evidence import proof_id
from .caption_role_semantics import continuation_title
from .numbered_structure_models import NumberedTableIssue
from .source_document import document_sha256
from .source_geometry import SourceTokens
from .structure_table_headers import possible_structure_header
from .unruled_continuation import observe_continuation
from .unruled_continuation_links import (
    compatible_diagram_scope,
    eligible_parents,
    repeated_header_covers,
)
from .unruled_continuation_titles import (
    anchor_scope,
    continuation_identity,
    continuation_nominees,
    nominated_table_keys,
)
from .unruled_region_observation import observe_region
from .unruled_scope import scope_axes
from .unruled_structure_headers import (
    nominate_unruled_headers,
    observe_unruled_header,
)
from .unruled_structure_layout import pair_evidence, region_plan


@dataclass(frozen=True)
class UnruledTableBinding:
    label: str
    structure: dict
    proof: dict

    def evidence(self):
        return self.proof


def observe_unruled_tables(
    doc, structures, pages, grids_for_page, tokens_for_page, *, page_texts=None
):
    bindings, sections, issues, protected, recognized, observed = (
        [],
        [],
        [],
        set(),
        set(),
        set(),
    )
    original_sha = None
    by_page, sections_by_page, anchors_by_key = {}, defaultdict(list), defaultdict(list)
    for structure in structures:
        by_page.setdefault(structure["page_no"] - 1, []).append(structure)
    for page_index in sorted(set(pages)):
        if type(page_index) is not int or not 0 <= page_index < len(doc):
            continue
        page = doc[page_index]
        # Legacy boxed-cell adapters cannot prove a new original page layout.
        if not callable(getattr(page, "get_image_info", None)):
            continue
        # Actual diagram pages always receive a source inspection. For pages
        # without detected diagrams, complete original page-text observations
        # nominate missing-structure tables without launching coordinate OCR on
        # unrelated prose. Hints cannot authorize or suppress a known diagram.
        if (
            page_index not in by_page
            and page_texts is not None
            and not (
                possible_structure_header(page_texts[page_index])
                or continuation_title(page_texts[page_index])
            )
        ):
            continue
        tokens = tokens_for_page(page)
        if not isinstance(tokens, SourceTokens):
            continue
        size = [page.rect.width, page.rect.height]
        physical = grids_for_page(page)
        nominees = [
            groups
            for groups in nominate_unruled_headers(tokens, size)
            if not any(
                grid["xs"][0] <= groups[0]["bbox"][0]
                and groups[-1]["bbox"][2] <= grid["xs"][-1]
                and grid["ys"][0]
                <= groups[0]["bbox"][1]
                < groups[0]["bbox"][3]
                <= grid["ys"][-1]
                for grid in physical
            )
        ]
        captions = continuation_nominees(tokens, size)
        if not nominees and not captions:
            continue
        available = {str(s["id"]): s for s in by_page.get(page_index, [])}
        page_diagrams = sorted(
            [
                {"id": str(s["id"]), "bbox": [s[k] for k in ("x0", "y0", "x1", "y1")]}
                for s in by_page.get(page_index, [])
            ],
            key=lambda item: (item["bbox"][1], item["bbox"][0], item["id"]),
        )
        headers = []
        for groups in nominees:
            if original_sha is None:
                original_sha = document_sha256(doc)
            header = observe_unruled_header(page, tokens, groups, original_sha)
            if header is None:
                raise ValueError(
                    "Original unruled header exceeds its observation budget"
                )
            headers.append(header)
        events = [(scope_axes(h)[1][0], h, None) for h in headers]
        events.extend(
            (caption["bbox"][1], None, caption)
            for caption in captions
            if not any(
                repeated_header_covers(h, page_diagrams, caption) for h in headers
            )
        )
        for _top, header, caption in sorted(events, key=lambda event: event[0]):
            if header is None:
                key = continuation_identity(caption["text"])[0]
                anchors = anchors_by_key[key]
                if not anchors:
                    continue  # Unrelated biology continuations cannot borrow structure roles.
                parents = eligible_parents(
                    [*sections_by_page[page_index], *sections_by_page[page_index + 1]],
                    page_index + 1,
                    key,
                    caption,
                )
                parent = parents[0] if len(parents) == 1 else None
                anchor = (
                    anchor_scope(parent["source"]["header_scope"])
                    if parent
                    else anchors[-1]
                )
                header = observe_continuation(page, tokens, caption, anchor, parent)
                if parent and not compatible_diagram_scope(
                    parent, header, page_diagrams
                ):
                    header["parent_region_id"], header["parent_page_no"] = "", None
            region = observe_region(page, tokens, header, page_diagrams)
            _roles, assignments, findings = region_plan(region)
            region_id = proof_id(region)
            section = {
                "role": "unruled_structure_region",
                "status": region["status"],
                "page_no": page_index + 1,
                "region_id": region_id,
                "source": region,
            }
            sections.append(section)
            sections_by_page[page_index + 1].append(section)
            for key in nominated_table_keys(header):
                anchors_by_key[key].append(anchor_scope(header))
            recognized.add(page_index)
            protected.update(d["id"] for d in region["diagrams"])
            observed.update(
                label["value"] for label in region["labels"] if label["value"]
            )
            issues.extend(
                NumberedTableIssue(
                    page_index,
                    finding["cpd"],
                    finding["reason"],
                    {"source_reference_region": region_id},
                )
                for finding in findings
            )
            for label, diagram in assignments:
                proof = pair_evidence(region, region_id, label, diagram)
                bindings.append(
                    UnruledTableBinding(
                        proof["source_label"], available[proof["structure_id"]], proof
                    )
                )
    return bindings, sections, issues, protected, recognized, observed
