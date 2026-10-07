"""Original header roles and recheckable row ownership, independent of width."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from itertools import pairwise

_IDENTIFIER = re.compile(
    r"(?:Cmpd|Cpd|Compound|Example|Ex|实施例|化合物)\.?\s*(?:No\.?|ID|#|编号|号)?|No\.?|ID|编号",
    re.IGNORECASE,
)
_STRUCTURE = re.compile(
    r"(?:(?:Chemical|Molecular)\s+)?Structures?(?:\s+(?:formula|drawing))?|化学结构|结构式|结构|構造式",
    re.IGNORECASE,
)


def structure_column_pairs(headers: Sequence[str]) -> tuple[tuple[int, int], ...]:
    normalized = [
        re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(h))).strip()
        for h in headers
    ]
    ids = [i for i, text in enumerate(normalized) if _IDENTIFIER.fullmatch(text)]
    structures = [i for i, text in enumerate(normalized) if _STRUCTURE.fullmatch(text)]
    if len(ids) == len(structures) == 1:
        return ((ids[0], structures[0]),)
    pairs = []
    for index, identifier in enumerate(ids):
        end = ids[index + 1] if index + 1 < len(ids) else len(headers)
        owned = [s for s in structures if identifier < s < end]
        if len(owned) != 1:
            return ()
        pairs.append((identifier, owned[0]))
    return tuple(pairs) if len(pairs) == len(structures) else ()


def valid_column_ownership(evidence: object, label_box, structure_box) -> bool:
    """A nonadjacent cell needs actual header roles, not same-y proximity."""
    if not isinstance(evidence, Mapping) or not label_box or not structure_box:
        return False
    try:
        xs, headers = evidence["grid_xs"], evidence["headers"]
        identifier, structure = (
            evidence["identifier_column"],
            evidence["structure_column"],
        )
        if (
            not isinstance(xs, list)
            or not 3 <= len(xs) <= 65
            or not isinstance(headers, list)
            or len(headers) != len(xs) - 1
        ):
            return False
        if any(
            type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in xs
        ) or any(b <= a for a, b in pairwise(xs)):
            return False
        if any(not isinstance(text, str) or len(text) > 1000 for text in headers):
            return False
        if (
            type(identifier) is not int
            or type(structure) is not int
            or (identifier, structure) not in structure_column_pairs(headers)
        ):
            return False
        return all(
            math.isclose(a, b, abs_tol=0.01)
            for a, b in zip(
                [
                    label_box[0],
                    label_box[2],
                    structure_box[0],
                    structure_box[2],
                    label_box[1],
                    label_box[3],
                ],
                [
                    xs[identifier],
                    xs[identifier + 1],
                    xs[structure],
                    xs[structure + 1],
                    structure_box[1],
                    structure_box[3],
                ],
            )
        )
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return False
