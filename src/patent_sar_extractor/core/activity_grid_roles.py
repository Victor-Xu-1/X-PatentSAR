"""Literal whole-grid characterization roles, never absence or result inference."""

import re

from .activity_header_metrics import METRIC, normalize_metric_text
from .activity_headers import ACTIVITY_CONTEXT, context_from_text
from .printed_identifiers import LABEL_KIND, PRINTED_ID, identifier_key
from .role_grid_windows import MAX_ROLE_COLUMNS, MAX_ROLE_GRID_CELLS
from .source_role_terms import INTERMEDIATE_SINGULAR
from .source_section_roles import section_heading

MAX_ROLE_TEXT_ROWS = 32
MAX_ROLE_ROW_HEIGHT = 32
_ID_HEADER = re.compile(
    rf"(?:Compound|Cmpd|Cpd|{INTERMEDIATE_SINGULAR}|Example|化合物|实施例)\s*(?:No\.?|ID|#|编号)?|No\.|ID|编号",
    re.IGNORECASE,
)
_ID_LABEL = re.compile(
    rf"(?:Compound|Cmpd|Cpd|{INTERMEDIATE_SINGULAR}|Example|化合物|实施例)\s*({PRINTED_ID})",
    re.IGNORECASE,
)
_PREPARATION = re.compile(
    r"\b(?:synthesized|prepared)\s*"
    r"(?:in\s*analogy\s*to|according\s*to|by\s*the\s*(?:method|procedure))"
    rf"(?:\b|(?={LABEL_KIND}(?=\s|\d)))|"
    r"(?:合成|制备)(?:方法)?(?:同|参照|按照)",
    re.IGNORECASE,
)
_NMR = re.compile(r"(?<![A-Za-z])(?:\d{1,3}\s*[HCFPN]\s*)?NMR\b", re.IGNORECASE)
_SPECTRAL_UNIT = re.compile(r"(?<![A-Za-z])(?:MHz|ppm)(?![A-Za-z])", re.IGNORECASE)
_CHARACTERIZATION_TITLE = re.compile(
    r"\b(?:characterization|characterisation)\b|结构表征", re.IGNORECASE
)
_MASS = re.compile(r"\b(?:HRMS|MS)\b.*?m\s*/?\s*z\b", re.IGNORECASE)
_ENDPOINT = re.compile(
    r"(?<![A-Za-z0-9])(?:p?IC50|EC50|DC50|GI50|CC50|Ki|Kd|Imax|Dmax|Ymin|Ymax|"
    r"Clint|Cmax|AUC|TGI|t1/2)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def compact(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def declared_measurement(text):
    """Nuclear 19 F / chloride fragments are not bare bioavailability/clearance."""
    normalized = normalize_metric_text(text)
    return bool(_ENDPOINT.search(normalized) or METRIC.fullmatch(compact(normalized)))


def nominate_characterization(matrix, prefix):
    """Cheap locator hints can be incomplete; they are never role proof."""
    if not isinstance(matrix, (list, tuple)) or not isinstance(prefix, str):
        return False
    texts = [
        cell
        for row in matrix
        if isinstance(row, (list, tuple))
        for cell in row
        if isinstance(cell, str)
    ]
    if sum(len(text) for text in texts) > 100000:
        return False
    text = compact(" ".join(texts))
    return bool(
        _PREPARATION.search(text)
        and (_NMR.search(text) or _MASS.search(text))
        or _CHARACTERIZATION_TITLE.search(prefix)
        and (_NMR.search(text) or _MASS.search(text))
        or matrix
        and isinstance(matrix[0], (list, tuple))
        and any(_ID_HEADER.fullmatch(compact(cell)) for cell in matrix[0])
        and _NMR.search(text)
        and _MASS.search(text)
    )


def characterization_roles(matrix, prefix):
    """Every physical column and row needs a positive supported role.

    Unsupported extra columns, empty cells, explicit biological context or
    endpoints remain unknown. Characterization never proves missing results.
    """
    if (
        not isinstance(matrix, (list, tuple))
        or not matrix
        or not isinstance(prefix, str)
        or len(prefix) > 10000
    ):
        return None
    width = len(matrix[0]) if isinstance(matrix[0], (list, tuple)) else 0
    if not 1 <= width <= MAX_ROLE_COLUMNS or len(matrix) * width > MAX_ROLE_GRID_CELLS:
        return None
    if any(
        not isinstance(row, (list, tuple))
        or len(row) != width
        or any(not isinstance(text, str) or len(text) > 4096 for text in row)
        for row in matrix
    ):
        return None
    context = context_from_text(prefix, prefix)
    if context.raw_caption:
        if ACTIVITY_CONTEXT.search(context.raw_caption) or METRIC.search(
            normalize_metric_text(context.raw_caption)
        ):
            return None
    else:
        headings = [section_heading(line) for line in prefix.splitlines()]
        last = next((heading for heading in reversed(headings) if heading), None)
        if last and last["role"] == "assay_section":
            return None
    has_header = any(_ID_HEADER.fullmatch(compact(cell)) for cell in matrix[0])
    rows = matrix[1:] if has_header else matrix
    if not rows or any(declared_measurement(cell) for row in matrix for cell in row):
        return None
    if has_header and any(
        METRIC.search(normalize_metric_text(cell)) and not _NMR.search(cell)
        for cell in matrix[0]
    ):
        return None
    roles = []
    for column in range(width):
        texts = [compact(row[column]) for row in rows]
        if not all(texts):
            return None
        identifier = all(
            identifier_key(text, wrapped=True, terminal_period=True)
            or (match := _ID_LABEL.fullmatch(text))
            and identifier_key(match[1])
            for text in texts
        ) and (
            has_header
            and _ID_HEADER.fullmatch(compact(matrix[0][column]))
            or not has_header
            and all(_ID_LABEL.fullmatch(text) for text in texts)
        )
        if identifier:
            roles.append("identifier")
        elif all(_PREPARATION.search(text) for text in texts):
            roles.append("preparation")
        else:
            nmr = all(
                _NMR.search(text) and _SPECTRAL_UNIT.search(text) for text in texts
            )
            mass = all(_MASS.search(text) for text in texts)
            if not nmr and not mass:
                return None
            roles.append(
                "characterization" if nmr and mass else "nmr" if nmr else "mass"
            )
    declared = bool(_CHARACTERIZATION_TITLE.search(context.raw_caption))
    if roles.count("identifier") != 1 or not any(
        role in {"nmr", "mass", "characterization"} for role in roles
    ):
        return None
    if not declared and (
        "preparation" not in roles
        or not any(role in {"nmr", "characterization"} for role in roles)
        or not any(role in {"mass", "characterization"} for role in roles)
    ):
        return None
    return {"data_start": int(has_header), "columns": roles}
