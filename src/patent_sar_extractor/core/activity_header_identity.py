"""Protect already observed scientific header/context identities from voting."""

import re

from .activity_context_values import (
    CONTEXT_IDENTITY_FIELDS,
    partial_context_value_matches,
)
from .activity_context_values import compact_context_value as compact_header
from .activity_header_metrics import (
    METRIC,
    explicit_unit,
    header_qualifier_text,
    literal_header_units,
    normalize_metric_text,
)
from .activity_headers import infer_value_keys
from .activity_identity import is_id_header
from .activity_metadata import metadata_role
from .ocr_claims import qualified_text_runs
from .structure_table_headers import structure_header_role


def schema_requires_review(schema) -> bool:
    """One unresolved-field policy for rows, header carry and source replay."""
    return bool(
        schema.needs_review
        or schema.context.claim_conflicts
        or (schema.header_resolution or {}).get("status") == "unresolved"
        or any(
            "unknown" in key.lower()
            or key == "compound_id"
            or key.startswith("compound_id [")
            for group in schema.groups
            for _, key in group.value_columns
        )
    )


def measurement_header_identity(text: str) -> str:
    """One literal column identity for source boundaries and frame exclusion."""
    if is_id_header(text):
        return "identifier"
    if structure_header_role(text) == "structure":
        return "structure"
    if METRIC.search(normalize_metric_text(text)):
        return "measurement:" + compact_header(text)
    role = metadata_role(text)
    return "metadata:" + role if role else ""


def measurement_header_roles(headers):
    roles = tuple(measurement_header_identity(text) for text in headers)
    return (
        roles
        if "identifier" in roles
        and all(roles)
        and "structure" not in roles
        and any(role.startswith("measurement:") for role in roles)
        else None
    )


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
        old_name = old_metric.group().split("(")[0].strip()
        new_name = new_metric.group().split("(")[0].strip()
        old_qualifier = header_qualifier_text(
            old[old_metric.start() + len(old_name) : old_end]
        )
        new_qualifier = header_qualifier_text(
            new[new_metric.start() + len(new_name) : new_end]
        )
        if old_qualifier and compact_header(old_qualifier) != compact_header(
            new_qualifier
        ):
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


def context_conflict(original, fresh, *, partial=False) -> bool:
    issues = original.claim_conflicts
    if partial:
        issues = tuple(item for item in issues if not item.endswith(":missing"))
    return bool(issues or fresh.claim_conflicts) or any(
        old
        and new
        and compact_header(old) != compact_header(new)
        and not (
            partial and field != "table_id" and partial_context_value_matches(old, new)
        )
        for field in CONTEXT_IDENTITY_FIELDS
        for old, new in [(getattr(original, field), getattr(fresh, field))]
    )


def detector_header_conflict(parts, fresh: str) -> bool:
    """Keep valid detector claims alongside complete physical line rereads."""
    runs = qualified_text_runs(parts)
    if runs is None:
        return True
    return any(
        header_conflict("\n".join(run), _fragment_comparison("\n".join(run), fresh))
        or _missing_literal_fragment("\n".join(run), fresh)
        or not literal_header_units("\n".join(run)).issubset(
            literal_header_units(fresh)
        )
        for run in runs
    )


def _fragment_comparison(original: str, fresh: str) -> str:
    """A detector run owns literal fragments, never absent surrounding words.

    Project only additional prefix words for the existing strict comparison.
    The entire observed prefix must survive contiguously, in order and at
    token boundaries. Endpoint order, per-endpoint units and every trailing
    qualifier remain in the original comparison; no scientific text is edited.
    Complete header identities do not use this projection.
    """
    old, new = normalize_metric_text(original), normalize_metric_text(fresh)
    before, after = METRIC.search(old), METRIC.search(new)
    if before is None or after is None:
        return fresh
    prefix = old[: before.start()].strip()
    if not prefix:
        return fresh
    pattern = r"\s+".join(re.escape(word) for word in prefix.split())
    if re.search(
        rf"(?<![\w/+-]){pattern}(?![\w/+-])", new[: after.start()], re.IGNORECASE
    ):
        return prefix + " " + new[after.start() :]
    return fresh


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
