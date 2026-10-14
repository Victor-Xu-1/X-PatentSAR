"""Bounded literal grade declarations; never assign numeric activity values."""

import re

from .activity_header_metrics import METRIC, explicit_unit, normalize_metric_text
from .source_table_markers import TABLE_MARKER

_START = re.compile(r"letter\s+codes?\s+for\s+(.{1,80}?)\s+include\s*:", re.IGNORECASE)
_INTRO = re.compile(r"letter\s+codes?\s+for\b", re.IGNORECASE)
_DEFINITION = re.compile(r"\b([A-G])\s*\(\s*([^)]{1,1000})\)", re.IGNORECASE)
_MOLAR_UNIT = re.compile(r"(?<![A-Za-z])[fpnumµμ]?M(?![A-Za-z])")


def _names(text):
    return [
        m.group().split("(")[0].strip().casefold()
        for m in METRIC.finditer(normalize_metric_text(text))
    ]


def matching_legend(legend, header):
    if not legend:
        return None
    return (
        legend
        if _names(legend[0]) == _names(header) and len(_names(header)) == 1
        else None
    )


def read_legend(text, header=""):
    """Keep all original declarations in the source catalog; refuse conflicts.

    The returned mapping is annotation only, never a grade-to-number conversion.
    Repeated declarations must agree literally. Different declared molar units
    require review rather than an implicit conversion of interval boundaries.
    """
    source = re.sub(r"\s+", " ", text)
    starts = list(_START.finditer(source))
    if len(starts) > 32:
        raise ValueError("Original grade declarations exceed their bounded scope")
    definitions, metric, issues = {}, "", []
    if len(_INTRO.findall(source)) != len(starts):
        issues.append("Unsupported original grade declaration")
    for index, start in enumerate(starts):
        label = start.group(1).strip()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(source)
        tail = source[start.end() : end]
        marker = TABLE_MARKER.search(tail)
        if marker:
            tail = tail[: marker.start()]
        pairs = _DEFINITION.findall(tail)
        if len(pairs) > 32:
            raise ValueError("Original grade definitions exceed their bounded scope")
        if not METRIC.search(normalize_metric_text(label)) or len(pairs) < 2:
            issues.append("Unsupported original grade declaration")
        if metric and _names(metric) != _names(label):
            issues.append("Conflicting original grade endpoints")
        metric = metric or label
        for grade, definition in pairs:
            grade, definition = grade.upper(), definition.strip()
            if grade in definitions and definitions[grade] != definition:
                issues.append("Conflicting original grade definitions")
            else:
                definitions[grade] = definition
    if not starts:
        return None, issues
    candidate = (metric, definitions)
    if header and not matching_legend(candidate, header):
        issues.append("Grade declaration does not own the original endpoint")
    units = {
        unit.replace("µ", "u").replace("μ", "u")
        for value in definitions.values()
        for unit in _MOLAR_UNIT.findall(value)
    }
    printed = {
        unit.replace("µ", "u").replace("μ", "u")
        for m in METRIC.finditer(normalize_metric_text(header))
        for part in re.findall(r"\(([^()]*)\)", m.group())
        if (unit := explicit_unit(part))
    }
    if len(units) > 1 or units and printed and units != printed:
        issues.append("Conflicting original grade and header units")
    return (None if issues else candidate), list(dict.fromkeys(issues))
