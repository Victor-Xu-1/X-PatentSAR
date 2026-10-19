"""One bounded literal declaration authority for original experimental contexts."""

import re
from itertools import islice

from .activity_header_metrics import normalize_metric_text

SCIENTIFIC_CONTEXT_FIELDS = (
    "target",
    "assay",
    "cell_line",
    "construct",
    "duration",
    "treatment_duration",
    "timepoint",
    "batch",
)
CONTEXT_IDENTITY_FIELDS = ("table_id", *SCIENTIFIC_CONTEXT_FIELDS)
CONTEXT_TEXT_FIELDS = ("caption", "raw_caption", "body_text", "raw_context")
UNKNOWN_CONTEXT = {"", "unknown", "not recorded", "not specified"}

_LABELS = {
    "target": r"Target|靶点",
    "assay": r"Assay(?:[ \t]+name)?|实验方法|实验",
    "cell_line": r"Cell[ -]+line|细胞系|细胞株",
    "construct": r"Construct|构建体",
    "duration": r"Duration|处理时长",
    "treatment_duration": r"Treatment[ \t]+duration|处理持续时间",
    "timepoint": r"Time[ -]?point|时间点",
    "batch": r"Batch|批次",
}
_DECLARATION = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(f"(?P<{key}>{value})" for key, value in _LABELS.items())
    + r")[ \t]*[:：][ \t]*",
    re.IGNORECASE,
)
_CELL_NAMES = re.compile(
    r"\b([A-Za-z][A-Za-z0-9-]{1,20})\s+cells\b|([A-Za-z][A-Za-z0-9-]{1,20})细胞"
)
_CELL_DESCRIPTORS = frozenset(
    {
        "the",
        "these",
        "those",
        "all",
        "both",
        "each",
        "other",
        "some",
        "human",
        "mouse",
        "murine",
        "rat",
        "primary",
        "stem",
        "tumor",
        "cancer",
        "treated",
        "untreated",
        "control",
        "test",
        "transfected",
        "derived",
        "monocyte-derived",
        "remaining",
        "cultured",
        "seeded",
        "incubated",
    }
)


def compact_context_value(value: str) -> str:
    """Existing literal typography comparison only, never scientific rewriting."""
    text = normalize_metric_text(value)
    text = re.sub(r"(?<![A-Za-z0-9])[µμ]M(?![A-Za-z0-9])", "uM", text)
    return "".join(text.split()).casefold()


def missing_context_value(value):
    return value is None or value.strip().casefold() in UNKNOWN_CONTEXT


def normalized_context_conditions(values):
    """One existing treatment-duration alias rule, preserving all raw carriers."""
    result = dict(values)
    treatment = result.get("treatment_duration")
    if missing_context_value(treatment):
        result.pop("treatment_duration", None)
        return result
    duration = result.get("duration")
    if not missing_context_value(duration) and duration != treatment:
        raise ValueError("Conflicting original duration declarations")
    result["duration"] = treatment if missing_context_value(duration) else duration
    result.pop("treatment_duration", None)
    return result


def validate_context_record(context, table_id):
    """One persisted context shape for ordinary and transposed original tables."""
    if (
        not isinstance(context, dict)
        or set(context) != {*CONTEXT_IDENTITY_FIELDS, *CONTEXT_TEXT_FIELDS}
        or any(
            value is None
            and key not in SCIENTIFIC_CONTEXT_FIELDS
            or value is not None
            and (not isinstance(value, str) or len(value) > 10000)
            for key, value in context.items()
        )
        or context["table_id"] != table_id
    ):
        raise ValueError("Malformed original table context")


def partial_context_value_matches(original: str, fresh: str) -> bool:
    """A qualified partial declaration owns a literal prefix, not absent words."""
    pattern = r"\s+".join(
        re.escape(word) for word in normalize_metric_text(original).split()
    )
    return bool(
        pattern
        and re.match(
            pattern + r"(?![\w/+-])",
            normalize_metric_text(fresh).strip(),
            re.IGNORECASE,
        )
    )


def _declaration_value(content):
    if content.startswith(("\n", "\r\n")):
        content = content.removeprefix("\r").removeprefix("\n")
    parts = re.split(r"[;；\r\n]", content, maxsplit=1)
    return parts[0].strip(" \t,"), parts[1] if len(parts) == 2 else ""


def declared_context_suffix(source):
    """Separate only fully consumed literal declarations after a printed title.

    Free prose, unknown labels, missing values and conflicting declarations are
    not removable context. Callers must still prove the actual continued title,
    source confidence, physical ancestry and equality to known parent values.
    """
    if len(source) > 10000:
        return None
    declarations = list(islice(_DECLARATION.finditer(source), 33))
    if not declarations:
        return source, {}
    if len(declarations) > 32:
        return None
    for index, declaration in enumerate(declarations):
        end = (
            declarations[index + 1].start()
            if index + 1 < len(declarations)
            else len(source)
        )
        _, remaining = _declaration_value(source[declaration.end() : end])
        if remaining.strip(" \t\r\n;；,"):
            return None
    values, issues = context_values(source[declarations[0].start() :])
    if issues:
        return None
    return source[: declarations[0].start()].rstrip(" \t;；,"), values


def context_values(
    source: str, *, partial=False
) -> tuple[dict[str, str | None], tuple[str, ...]]:
    """Read declarations only inside the caller's already-owned caption window.

    Caption descriptions never become an assay name. Repeated identical labels
    are one claim; contradictory, empty or over-limit claims stay unresolved.
    Raw text stays in TableContext, including all losing/conflicting declarations.
    """
    values = dict.fromkeys(SCIENTIFIC_CONTEXT_FIELDS)
    if len(source) > 10000:  # Same existing original-context carrier bound.
        return values, ("context_text_limit",)
    declarations = list(islice(_DECLARATION.finditer(source), 33))
    if len(declarations) > 32:
        return values, ("context_declaration_limit",)
    claims: dict[str, dict[str, str]] = {key: {} for key in values}
    errors, invalid = set(), set()
    for index, declaration in enumerate(declarations):
        key = declaration.lastgroup
        end = (
            declarations[index + 1].start()
            if index + 1 < len(declarations)
            else len(source)
        )
        content = source[declaration.end() : end]
        # A labelled value may start on the immediately following printed line.
        # The next declaration is already excluded by `end`; no earlier table
        # or later free paragraph is searched to fill an empty value.
        value, _ = _declaration_value(content)
        if not value:
            errors.add(key + ":missing")
            if not partial:
                invalid.add(key)
        elif len(value) > (300 if key == "target" else 1000) or "\x00" in value:
            errors.add(key + ":limit")
            invalid.add(key)
        else:
            claims[key].setdefault(compact_context_value(value), value)
    # Preserve the existing unlabelled-cell reader only when no explicit cell
    # line owns this field. It cannot replace a declared cell line or pick the
    # final one from conflicting observations.
    if not any(item.lastgroup == "cell_line" for item in declarations):
        for first, second in _CELL_NAMES.findall(source):
            value = first or second
            # Literal identifier/proper-name shape, not an arbitrary word before
            # "cells". Generic pronouns/population descriptions are not cell lines.
            if value.casefold() not in _CELL_DESCRIPTORS and (
                any(char.isupper() or char.isdigit() for char in value)
            ):
                claims["cell_line"].setdefault(compact_context_value(value), value)
    for key, choices in claims.items():
        if len(choices) > 1:
            errors.add(key + ":conflict")
        elif choices and key not in invalid:
            values[key] = next(iter(choices.values()))
    try:
        normalized_context_conditions(values)
    except ValueError:
        errors.add("duration:conflict")
    return values, tuple(sorted(errors))
