"""Narrow original-title constraints, never a general OCR conflict override."""

import re

from .caption_role_semantics import catalog_title_role, closed_catalogue_category
from .source_observations import source_observation_status
from .source_role_terms import role_words

_CATEGORY_WORDS = frozenset(
    [
        "compound",
        "compounds",
        "example",
        "examples",
        "intermediate",
        "intermediates",
        "product",
        "products",
        "reactant",
        "reactants",
        "reagent",
        "reagents",
        "material",
        "materials",
        "block",
        "blocks",
    ]
)


def title_tokens(text):
    # Expose only existing literal word/case boundaries. Preserve all numbers,
    # punctuation and every non-role word; do not normalize an identifier.
    return tuple(re.findall(r"[^\W\d_]+|\d+|[^\s]", role_words(text).casefold()))


def eligible_title_literal(proof):
    """One known whole category + one unknown word, both tied to a known locator.

    A qualified raster nomination and one complete primary must already agree
    literally. A second complete primary may have exactly one UNKNOWN category
    word; known opposite roles/negation/table numbers/other words never qualify.
    Native/hybrid claims and all measurements remain on their existing path.
    """
    from .title_source_proof import title_source_inputs

    if title_source_inputs(proof) is None or proof.get("version") != 2:
        return None
    raw, native = proof["nomination_source"], proof["native_source"]
    readings, frames = proof["observations"], proof["rendered_frames"]
    if (
        raw["origin"] != "raster"
        or source_observation_status(raw, raw["bbox"], raw["text"]) != "qualified"
        or closed_catalogue_category(raw["text"]) is None
        or native["text"].strip()
        or native["tokens"]
        or native.get("boundary_tokens")
        or len(readings) != 2
        or len(frames) != 2
    ):
        return None
    for reading in readings:
        if (
            "auxiliary_text" in reading
            or "source_window" not in reading
            or len(reading.get("parts", [])) != 1
        ):
            return None
    known = [
        reading["raw_text"]
        for reading in readings
        if closed_catalogue_category(reading["raw_text"])
    ]
    if len(known) != 1 or title_tokens(known[0]) != title_tokens(raw["text"]):
        return None
    candidate = known[0]
    other = next(
        reading["raw_text"] for reading in readings if reading["raw_text"] != candidate
    )
    if catalog_title_role(other) != "unknown":
        return None
    expected, observed = title_tokens(candidate), title_tokens(other)
    if len(expected) != len(observed):
        return None
    differences = [(a, b) for a, b in zip(expected, observed, strict=True) if a != b]
    if len(differences) != 1:
        return None
    good, uncertain = differences[0]
    return candidate if good in _CATEGORY_WORDS and uncertain.isalpha() else None
