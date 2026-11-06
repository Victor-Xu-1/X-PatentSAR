"""A bounded original reaction input label may qualify one boundary projection.

The original page inventory remains intact. A projection is usable only with
the existing complete source-arrow graph and an independently visible literal
caption. It never creates an identifier, excludes a diagram, or ranks products.
"""

import re

from .native_title_claims import title_literal
from .native_window_coverage import native_window_complete, observe_native_window
from .source_evidence_identity import proof_id
from .source_geometry import SourceTokens, source_layout
from .source_observations import source_cell_observation, source_observation_status
from .source_paint_visibility import native_paint_view, visible_native_tokens
from .source_role_terms import INTERMEDIATE_SINGULAR
from .title_geometry_memo import memoized_title_geometry
from .title_original_replay import replay_source_title
from .title_source_capture import observe_source_title
from .title_source_proof import source_title_text

_LABEL = re.compile(
    rf"^{INTERMEDIATE_SINGULAR}\s*[:：.\-]?\s*[A-Za-z0-9][A-Za-z0-9_-]{{0,31}}$",
    re.IGNORECASE,
)


def _projection(scope, heading):
    from .heading_declaration_scope import _page_valid, _stop

    if (
        not isinstance(scope, dict)
        or set(scope)
        != {
            "version",
            "status",
            "original_pdf_sha256",
            "heading_source_id",
            "document_page_count",
            "pages",
            "column_sources",
            "later_columns",
            "stop",
            "caption_witness",
        }
        or type(scope["version"]) is not int
        or scope["version"] != 5
        or scope["status"] != "observed_declaration"
        or scope["column_sources"] != []
        or scope["later_columns"] != []
        or not isinstance(scope["pages"], list)
        or len(scope["pages"]) != 1
        or not _page_valid(scope["pages"][0])
    ):
        raise ValueError("Malformed original reaction-caption declaration")
    witness = scope["caption_witness"]
    if (
        not isinstance(witness, dict)
        or set(witness) != {"line_index", "owner_id", "label_source", "reaction"}
        or type(witness["line_index"]) is not int
        or not isinstance(witness["owner_id"], str)
    ):
        raise ValueError("Malformed original reaction-caption witness")
    page = scope["pages"][0]
    index = witness["line_index"]
    if not 0 <= index < len(page["lines"]):
        raise ValueError("Original reaction-caption row is missing")
    line = page["lines"][index]
    if line["source"] not in {"native", "page_ocr"} or not _LABEL.fullmatch(
        line["text"].strip()
    ):
        raise ValueError("Reaction caption lacks a complete literal label")
    original_stop = _stop(page, heading)
    if original_stop != (line["bbox"][1], "source_boundary"):
        raise ValueError("Reaction caption is not the original earliest boundary")
    # A simultaneous boundary, even at a different horizontal position, cannot
    # be deleted by assigning this row to a reaction input.
    for other in page["lines"]:
        if other is line or other["bbox"][1] != line["bbox"][1]:
            continue
        single = {**page, "lines": [other]}
        if _stop(single, heading) is not None:
            raise ValueError("Competing original boundary shares the caption row")
    projected_page = {
        **page,
        "lines": page["lines"][:index] + page["lines"][index + 1 :],
    }
    boundary = _stop(projected_page, heading)
    if boundary is None:
        if page["page_no"] != scope["document_page_count"]:
            raise ValueError("Caption projection cannot assume a page ends a procedure")
        stop = {
            "kind": "document_end",
            "page_no": page["page_no"],
            "y": page["page_size"][1],
        }
    else:
        stop = {"kind": boundary[1], "page_no": page["page_no"], "y": boundary[0]}
    if scope["stop"] != stop:
        raise ValueError("Reaction-caption projection changed its next boundary")
    projected = {key: value for key, value in scope.items() if key != "caption_witness"}
    projected.update(version=3, pages=[projected_page])
    return projected, line, witness


def _caption_owner(line, candidates):
    label = line["bbox"]
    height = label[3] - label[1]
    center = (label[0] + label[2]) / 2
    owners = []
    for candidate in candidates:
        box = candidate["bbox"]
        gap = label[1] - box[3]
        horizontal = min(label[2], box[2]) - max(label[0], box[0])
        if (
            candidate["inside"]
            and box[0] <= center <= box[2]
            and horizontal >= (label[2] - label[0]) / 2
            and -1 <= gap <= 1.5 * height
        ):
            owners.append(candidate["structure_id"])
    if len(owners) != 1:
        raise ValueError("Reaction caption has no unique original diagram owner")
    return owners[0]


def reaction_caption_candidates(scope, heading):
    """Replay the complete graph and raw native caption before using a projection."""
    return memoized_title_geometry(
        {"scope": scope, "heading": heading},
        lambda source: _reaction_caption_candidates(source["scope"], source["heading"]),
    )


def _reaction_caption_candidates(scope, heading):
    from .heading_declaration_scope import declaration_candidates
    from .heading_reaction import reaction_source_status

    proof_id(scope)
    projected, line, witness = _projection(scope, heading)
    source = witness["label_source"]
    if not isinstance(source, dict):
        raise TypeError("Malformed reaction caption source")
    if line["source"] == "native":
        if (
            set(source) != {"method", "native", "window"}
            or source["method"] != "native"
            or source_observation_status(source["native"], line["bbox"], line["text"])
            != "qualified"
            or source["native"].get("origin") != "native"
            or not native_window_complete(source["window"], source["native"])
        ):
            raise ValueError("Reaction caption native source is unqualified")
    else:
        title = source.get("title")
        if (
            set(source) != {"method", "title"}
            or source["method"] != "raster"
            or not isinstance(title, dict)
            or title.get("page_no") != scope["pages"][0]["page_no"]
            or title.get("nomination_source", {}).get("bbox") != line["bbox"]
            or title.get("nomination_source", {}).get("text") != line["text"]
            or title.get("nomination_source", {}).get("origin") != "raster"
            or source_title_text(title) is None
            or title_literal(source_title_text(title)) != title_literal(line["text"])
        ):
            raise ValueError("Reaction caption raster source is unqualified or changed")
    candidates, complete = declaration_candidates(projected, heading)
    if not complete:
        raise ValueError("Reaction-caption declaration is incomplete")
    owner = _caption_owner(line, candidates)
    if owner != witness["owner_id"]:
        raise ValueError("Reaction caption owner differs from original geometry")
    route = witness["reaction"]
    terminal = reaction_source_status(route, projected, heading)
    inputs = {
        item
        for page in route.get("reactant_groups", [])
        for step in page["steps"]
        for item in step["input_ids"]
    }
    if owner == terminal or owner not in inputs:
        raise ValueError("Captioned diagram is not a proved explicit reaction input")
    return candidates, complete


def observe_reaction_caption_scope(document, scope, heading):
    """Try one caption; failure preserves the ordinary strict boundary."""
    from .heading_declaration_scope import _stop
    from .heading_reaction import observe_reaction_source

    if (
        scope.get("version") != 3
        or len(scope.get("pages", [])) != 1
        or scope.get("column_sources")
        or scope.get("later_columns")
    ):
        return None
    page = scope["pages"][0]
    boundary = _stop(page, heading)
    if boundary is None or boundary[1] != "source_boundary":
        return None
    indexes = [
        index
        for index, line in enumerate(page["lines"])
        if line["bbox"][1] == boundary[0]
        and line["source"] in {"native", "page_ocr"}
        and _LABEL.fullmatch(line["text"].strip())
    ]
    if len(indexes) != 1:
        return None
    index = indexes[0]
    line = page["lines"][index]
    original = document[page["page_no"] - 1]
    projected_page = {
        **page,
        "lines": page["lines"][:index] + page["lines"][index + 1 :],
    }
    following = _stop(projected_page, heading)
    if following is None:
        if page["page_no"] != scope["document_page_count"]:
            return None
        stop = {
            "kind": "document_end",
            "page_no": page["page_no"],
            "y": page["page_size"][1],
        }
    else:
        stop = {"kind": following[1], "page_no": page["page_no"], "y": following[0]}
    projected = {**scope, "pages": [projected_page], "stop": stop}
    from .heading_declaration_scope import declaration_candidates

    candidates, complete = declaration_candidates(projected, heading)
    if not complete:
        return None
    owner = _caption_owner(line, candidates)
    reaction = observe_reaction_source(document, projected, heading)
    inputs = {
        item
        for group in reaction.get("reactant_groups", [])
        for step in group["steps"]
        for item in step["input_ids"]
    }
    if owner == reaction["terminal_structure_id"] or owner not in inputs:
        return None
    label_source = _observe_label_source(original, line)
    if label_source is None:
        return None
    result = {
        **scope,
        "version": 5,
        "stop": stop,
        "caption_witness": {
            "line_index": index,
            "owner_id": owner,
            "label_source": label_source,
            "reaction": reaction,
        },
    }
    reaction_caption_candidates(result, heading)
    return result


def _observe_label_source(page, line):
    """Only read raster text after the complete route qualifies for a witness."""
    layout = source_layout(page)
    if line["source"] == "native":
        native = source_cell_observation(
            SourceTokens(layout.native, layout), line["bbox"], native=True
        )
        window = observe_native_window(page, line["bbox"])
        if not native_window_complete(window, native) or not visible_native_tokens(
            page, native
        ):
            return None
        return {"method": "native", "native": native, "window": window}
    box = line["bbox"]
    locator = {
        "text": line["text"],
        "bbox": box,
        "x": (box[0] + box[2]) / 2,
        "y": (box[1] + box[3]) / 2,
        "source": "raster",
        "geometry_space": "rendered",
    }
    nomination = source_cell_observation(
        SourceTokens([locator], layout, layout.raster_bounds), box
    )
    title = observe_source_title(
        page, nomination, layout=layout, paint_view=native_paint_view(page)
    )
    if source_title_text(title) is None or title_literal(
        source_title_text(title)
    ) != title_literal(line["text"]):
        return None
    return {"method": "raster", "title": title}


def replay_reaction_caption(document, scope, heading):
    """Reobserve original caption paint and the exact provisional route."""
    from .heading_reaction import observe_reaction_source

    reaction_caption_candidates(scope, heading)
    projected, line, witness = _projection(scope, heading)
    page = document[heading["page_no"] - 1]
    source = witness["label_source"]
    if source["method"] == "native":
        layout = source_layout(page)
        native = source_cell_observation(
            SourceTokens(layout.native, layout), line["bbox"], native=True
        )
        if (
            native != source["native"]
            or observe_native_window(page, line["bbox"]) != source["window"]
            or not visible_native_tokens(page, native)
        ):
            raise ValueError("Reaction caption native paint differs")
    else:
        replay_source_title(page, source["title"])
    if observe_reaction_source(document, projected, heading) != witness["reaction"]:
        raise ValueError("Reaction caption differs from its original source")
