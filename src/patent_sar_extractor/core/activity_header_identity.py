"""Protect already observed scientific header/context identities from voting."""

import re

from .activity_header_metrics import (
    METRIC,
    explicit_unit,
    literal_header_units,
    normalize_metric_text,
)
from .activity_headers import infer_value_keys
from .activity_metadata import metadata_role
from .ocr_claims import qualified_text_runs


def compact_header(value: str) -> str:
    text = normalize_metric_text(value)
    # Micro-unit glyph equivalence is comparison only; original text survives.
    text = re.sub(r"(?<![A-Za-z0-9])[µμ]M(?![A-Za-z0-9])", "uM", text)
    return "".join(text.split()).casefold()


def header_conflict(original: str, fresh: str) -> bool:
    old_role, new_role = metadata_role(original), metadata_role(fresh)
    if (old_role or new_role) and original.strip() and old_role != new_role:
        return True
    old, new = normalize_metric_text(original), normalize_metric_text(fresh)
    before, after = list(METRIC.finditer(old)), list(METRIC.finditer(new))
    if not before:
        return not literal_header_units(old).issubset(literal_header_units(new))

    def endpoints(matches):
        return tuple(m.group().split("(")[0].strip().casefold() for m in matches)

    if endpoints(before) != endpoints(after):
        return True
    # Preserve unit ownership per printed endpoint, not just a global unit set.
    # IC50(nM)/EC50(uM) cannot silently become IC50(uM)/EC50(nM).
    for index, (old_metric, new_metric) in enumerate(zip(before, after, strict=True)):
        old_end = before[index + 1].start() if index + 1 < len(before) else len(old)
        new_end = after[index + 1].start() if index + 1 < len(after) else len(new)
        units = literal_header_units(old[old_metric.start() : old_end])
        if units and units != literal_header_units(new[new_metric.start() : new_end]):
            return True
    key = infer_value_keys("", original, 1)[0]
    if "unknown" not in key.lower():
        # An endpoint/unit fragment does not assert an absent target/assay.
        # Project only that missing prefix for comparison; observed prefixes,
        # units, endpoint order and trailing qualifiers remain unchanged.
        compared = (
            fresh if old[: before[0].start()].strip() else new[after[0].start() :]
        )
        return compact_header(key) != compact_header(
            infer_value_keys("", compared, 1)[0]
        )
    # A missing unit is not permission to change an observed target/condition.
    old_prefix, new_prefix = old[: before[0].start()], new[: after[0].start()]
    if old_prefix.strip() and compact_header(old_prefix) != compact_header(new_prefix):
        return True
    old_units = {
        explicit_unit(m.group(1)) for m in re.finditer(r"\(([^()]*)\)", old)
    } - {None}
    new_units = {
        explicit_unit(m.group(1)) for m in re.finditer(r"\(([^()]*)\)", new)
    } - {None}
    return bool(old_units and old_units != new_units)


def context_conflict(original, fresh) -> bool:
    return any(
        old and new and compact_header(old) != compact_header(new)
        for field in ("table_id", "target", "assay", "cell_line")
        for old, new in [(getattr(original, field), getattr(fresh, field))]
    )


def detector_header_conflict(parts, fresh: str) -> bool:
    """Keep valid detector claims alongside complete physical line rereads."""
    runs = qualified_text_runs(parts)
    if runs is None:
        return True
    return any(
        header_conflict("\n".join(run), fresh)
        or _missing_literal_fragment("\n".join(run), fresh)
        or not literal_header_units("\n".join(run)).issubset(
            literal_header_units(fresh)
        )
        for run in runs
    )


def _missing_literal_fragment(original: str, fresh: str) -> bool:
    """A qualified isolated context word is not lost beside a weak endpoint.

    No role or target is inferred. Keep the whole literal fragment at token
    boundaries, permitting only the existing metric typography/whitespace rules.
    Endpoint and unit claims use their semantic guards above instead.
    """
    old, new = normalize_metric_text(original), normalize_metric_text(fresh)
    if METRIC.search(old) or not old.strip():
        return False
    # A unit alongside a context word is not permission to ignore that word.
    # Unit-only fragments use the existing unit guard, including micro glyphs.
    words = [
        word
        for word in re.split(r"(\([^()]*\))|\s+", old)
        if word and word.strip() and explicit_unit(word) is None
    ]
    if not words:
        return False
    literal = r"\s+".join(re.escape(word) for word in words)
    return re.search(rf"(?<!\w){literal}(?!\w)", new, re.IGNORECASE) is None
