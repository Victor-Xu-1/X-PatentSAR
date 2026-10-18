"""Capture catalogue roles from the existing original context authority."""

from .activity_context_geometry import (
    context_floor,
    context_region,
    grid_axes,
    grid_box,
)
from .caption_role_proof import observed_role
from .caption_role_titles import project_caption_titles
from .caption_title_refinement import observe_title_refinement, refined_title_role
from .source_geometry import SourceTokens, native_region
from .source_observations import source_cell_observation


def _proved_prefixed_frame(page, region, role, kinds, original_bindings):
    """Unknown titles need every literal caption cell, not a geometry exemption."""
    from .caption_binding_proof import valid_caption_binding_evidence

    if not {"label", "drawing"}.issubset(kinds) or any(
        kind not in {"label", "drawing"} for kind in kinds
    ):
        return False
    xs, ys = region["xs"], region["ys"]
    expected = {
        (xs[col], ys[row], xs[col + 1], ys[row + 1])
        for row, kind in enumerate(kinds)
        if kind == "label"
        for col in range(len(xs) - 1)
    }
    represented = set()
    for pair in original_bindings:
        ownership = pair["ownership"]
        cell = tuple(pair["label_bbox"])
        if (
            pair["label_page_no"] != page.number + 1
            or cell not in expected
            or cell in represented
            or ownership.get("caption_role") != role
            or "identifier_form" in ownership
        ):
            return False
        diagram = pair["structure"]
        binding = {
            "cpd": pair["label"],
            "structure_id": diagram["id"],
            "page_no": diagram["page_no"],
            **{"struct_" + axis: diagram[axis] for axis in ("x0", "y0", "x1", "y1")},
            "exact_caption_evidence": {
                "page_no": pair["label_page_no"],
                "bbox": list(pair["label_bbox"]),
                "observations": pair["observations"],
                "ownership": ownership,
            },
        }
        if not valid_caption_binding_evidence(binding):
            return False
        represented.add(cell)
    return bool(expected) and represented == expected


def owns_caption_frame(
    page, region, regions, tokens, boxes, *, original_role=None, original_bindings=()
):
    """A current original caption catalogue must not inherit unrelated columns."""
    from .caption_grid_rows import caption_rows
    from .caption_role_proof import caption_role_status

    role = observe_caption_role(
        page, region, regions, tokens, refine=original_role is None
    )
    if role is None:
        return False  # Untyped transport cannot prove a current caption owner.
    if original_role is not None:
        claimed = caption_role_status(original_role, page.number + 1, grid_box(region))
        fields = {"role", "table_key", "continuation", "refinement"}
        if claimed not in {"compound", "nonfinal", "unknown"} or {
            key: value for key, value in original_role.items() if key not in fields
        } != {key: value for key, value in role.items() if key not in fields}:
            return False
        role = original_role
    status = caption_role_status(role, page.number + 1, grid_box(region))
    if status == "nonfinal":
        return True
    if status not in {"compound", "unknown"}:
        return False
    _rows, kinds = caption_rows(region, tokens, boxes, role)
    if status == "unknown":
        return _proved_prefixed_frame(page, region, role, kinds, original_bindings)
    return "label" in kinds and "drawing" in kinds


def observe_caption_role(page, region, regions, tokens, *, refine=True):
    """Reuse original context; unknown observed titles may use bounded cell reads."""
    if not isinstance(tokens, SourceTokens):
        return None
    geometry = context_region(region, [grid_box(item) for item in regions])[
        "context_geometry"
    ]
    window = [0, context_floor(geometry), page.rect.width, region["ys"][0]]
    if window[1] >= window[3]:
        return None
    native = native_region(tokens, window, False)
    sources = [source_cell_observation(tokens, window, native=native)]
    if not native:
        sources.append(source_cell_observation(tokens, window, native=True))
    observed = project_caption_titles(sources, geometry)
    role, key = observed_role(observed)
    scope = {
        "version": 1,
        "page_no": page.number + 1,
        "table_bbox": grid_box(region),
        "grid_axes": grid_axes(region),
        "context_geometry": geometry,
        "window": window,
        "observations": observed,
        "sources": sources,
        "role": role,
        "table_key": key,
    }
    if refine and role == "unknown":
        reading = observe_title_refinement(page, scope, tokens)
        if reading is not None:
            scope["refinement"] = reading
            selected = refined_title_role(scope)
            if selected is not None:
                scope["role"], scope["table_key"] = selected
    return scope
