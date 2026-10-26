"""Unruled columns join the existing original-cell owner and artifact writer."""

from collections import defaultdict
from dataclasses import dataclass

from .activity_context_geometry import grid_axes, grid_box
from .activity_header_evidence import proof_id
from .binding_progress import observed_items
from .caption_role_observation import owns_caption_frame
from .caption_role_semantics import has_continuation_caption
from .logical_column_partitions import nominate_unruled_headers, nomination_groups
from .numbered_structure_models import NumberedTableIssue
from .ruled_column_continuation import observe_physical_continuation
from .ruled_continuation_links import (
    eligible_physical_parents,
    physical_parent_context_start,
)
from .ruled_structure_headers import observe_ruled_header
from .source_body_context import contained_source_diagrams
from .source_document import document_sha256
from .source_geometry import SourceTokens
from .structure_column_anchors import (
    ANCHOR_ROLE,
    column_anchor_diagrams,
    column_anchor_roles,
    observe_column_anchor,
)
from .structure_frame_observation import (
    known_measurement_frame,
    nominate_physical_frames,
)
from .structure_table_headers import aligned_column_edges, possible_structure_header
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
from .unruled_structure_headers import observe_unruled_header
from .unruled_structure_layout import pair_evidence, region_plan


@dataclass(frozen=True)
class UnruledTableBinding:
    label: str
    structure: dict
    proof: dict

    def evidence(self):
        return self.proof


def observe_unruled_tables(
    doc,
    structures,
    pages,
    grids_for_page,
    tokens_for_page,
    *,
    page_texts=None,
    caption_roles=None,
    caption_frames=None,
    progress=None,
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
    for page_index in observed_items("numbered_sources", sorted(set(pages)), progress):
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
            and not sections_by_page.get(page_index)
            and page_texts is not None
            and not (
                possible_structure_header(page_texts[page_index])
                or has_continuation_caption(page_texts[page_index])
            )
        ):
            continue
        tokens = tokens_for_page(page)
        if not isinstance(tokens, SourceTokens):
            continue
        size = [page.rect.width, page.rect.height]
        page_diagrams = sorted(
            [
                {"id": str(s["id"]), "bbox": [s[k] for k in ("x0", "y0", "x1", "y1")]}
                for s in by_page.get(page_index, [])
            ],
            key=lambda item: (item["bbox"][1], item["bbox"][0], item["id"]),
        )
        grids = [grid_axes(grid) for grid in grids_for_page(page)]
        physical, pending = nominate_physical_frames(
            tokens, grids, page_diagrams, sections_by_page[page_index], size
        )
        pending = [
            grid
            for grid in pending
            if not owns_caption_frame(
                page,
                grid,
                grids,
                tokens,
                [d["bbox"] for d in page_diagrams],
                original_role=(caption_roles or {}).get(
                    (page_index + 1, tuple(grid_box(grid)))
                ),
                original_bindings=(caption_frames or {}).get(
                    (page_index + 1, tuple(grid_box(grid))), ()
                ),
            )
        ]
        nominees = [
            nomination
            for nomination in nominate_unruled_headers(tokens, size)
            if not all(
                any(
                    grid["xs"][0] <= group["bbox"][0]
                    and group["bbox"][2] <= grid["xs"][-1]
                    and grid["ys"][0]
                    <= group["bbox"][1]
                    < group["bbox"][3]
                    <= grid["ys"][-1]
                    for grid in physical
                )
                for group in nomination_groups(nomination)
            )
        ]
        captions = continuation_nominees(tokens, size)
        if not nominees and not captions and not physical and not pending:
            continue
        available = {str(s["id"]): s for s in by_page.get(page_index, [])}
        headers = []
        if original_sha is None and (nominees or physical or pending):
            original_sha = document_sha256(doc)
        for nomination in nominees:
            header = observe_unruled_header(
                page, tokens, nomination, original_sha, grids=grids
            )
            if header is None:
                raise ValueError(
                    "Original unruled header exceeds its observation budget"
                )
            headers.append(header)
        title_observations = {}
        anchors = [
            observe_ruled_header(
                page,
                tokens,
                grid,
                original_sha,
                grids=grids,
                title_cache=title_observations,
            )
            for grid in physical
        ]
        events = [(scope_axes(h)[1][0], h, None, False, None) for h in headers]
        events.extend(
            (scope_axes(h)[1][0], h, None, len(h["grid_axes"]["ys"]) > 2, None)
            for h in anchors
        )
        events.extend(
            (caption["bbox"][1], None, caption, False, None)
            for caption in captions
            if not any(
                repeated_header_covers(h, page_diagrams, caption)
                for h in headers + anchors
            )
        )
        events.extend((grid["ys"][0], None, None, True, grid) for grid in pending)
        for _top, header, caption, anchor_only, row_grid in sorted(
            events, key=lambda event: event[0]
        ):
            if header is None and caption is None:
                if any(
                    s["role"] == ANCHOR_ROLE and s["source"]["grid_axes"] == row_grid
                    for s in sections_by_page[page_index + 1]
                ):
                    continue
                xs, ys = row_grid["xs"], row_grid["ys"]
                diagrams = contained_source_diagrams(
                    page_diagrams, [xs[0], ys[0], xs[-1], ys[-1]]
                )
                if not diagrams and known_measurement_frame(
                    page, tokens, row_grid, original_sha
                ):
                    continue
                header = observe_physical_continuation(
                    page, tokens, row_grid, grids, original_sha
                )
                parents = eligible_physical_parents(
                    [*sections_by_page[page_index], *sections_by_page[page_index + 1]],
                    header,
                    page_diagrams,
                )
                if len(parents) == 1:
                    parent = parents[0]
                    header.update(
                        anchor_scope=anchor_scope(parent["source"]["header_scope"]),
                        parent_region_id=parent["region_id"],
                        parent_page_no=parent["page_no"],
                        context_start=physical_parent_context_start(parent, header),
                    )
            elif header is None:
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
                xs, ys = scope_axes(header)
                matching = [
                    g
                    for g in pending
                    if aligned_column_edges(xs, g["xs"]) and g["ys"][0] >= ys[1]
                ]
                if len(matching) == 1:
                    anchor_only, row_grid = True, matching[0]
            if anchor_only:
                region = observe_column_anchor(
                    tokens, header, page_diagrams, grid=row_grid
                )
                column_anchor_roles(region)
                assignments, findings = [], []
            else:
                region = observe_region(page, tokens, header, page_diagrams)
                _roles, assignments, findings = region_plan(region)
            region_id = proof_id(region)
            section = {
                "role": ANCHOR_ROLE if anchor_only else "unruled_structure_region",
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
            if anchor_only:
                protected.update(d["id"] for d in column_anchor_diagrams(region))
                continue
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
