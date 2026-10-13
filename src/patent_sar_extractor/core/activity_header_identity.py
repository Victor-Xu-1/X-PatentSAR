"""Protect already observed scientific header/context identities from voting."""

import re

from .activity_header_metrics import METRIC, explicit_unit, normalize_metric_text
from .activity_headers import infer_value_keys


def compact_header(value: str) -> str:
    text = normalize_metric_text(value)
    # Micro-unit glyph equivalence is comparison only; original text survives.
    text = re.sub(r"(?<![A-Za-z0-9])[µμ]M(?![A-Za-z0-9])", "uM", text)
    return "".join(text.split()).casefold()


def header_conflict(original: str, fresh: str) -> bool:
    old, new = normalize_metric_text(original), normalize_metric_text(fresh)
    before, after = list(METRIC.finditer(old)), list(METRIC.finditer(new))
    if not before:
        return False

    def endpoints(matches):
        return tuple(m.group().split("(")[0].strip().casefold() for m in matches)

    if endpoints(before) != endpoints(after):
        return True
    key = infer_value_keys("", original, 1)[0]
    if "unknown" not in key.lower():
        return compact_header(key) != compact_header(infer_value_keys("", fresh, 1)[0])
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
