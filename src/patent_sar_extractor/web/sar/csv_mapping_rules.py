"""One conservative header-role authority; no numeric-cell activity guessing."""

from __future__ import annotations

import re
import unicodedata

from ...core.activity_header_metrics import METRIC
from ..indicator_conventions import numeric_direction
from ..lead_endpoints import LEAD_ENDPOINTS
from .csv_preview_models import CSVMappingDefaults
from .csv_scope import native_headers

_PREFERRED_ID = {"identifierlabel", "displayid", "label", "原文编号"}
_ID = _PREFERRED_ID | {
    "compoundid",
    "compoundnumber",
    "compound",
    "id",
    "编号",
    "化合物编号",
    "化合物",
}
_SMILES = {"smiles", "canonicalsmiles", "isomericsmiles"}
_VALUE = {"value", "activityvalue", "measurementvalue", "活性值", "数值"}
_COLUMNS = {
    "metric_column": {"metric", "endpoint", "metricname", "指标名称", "活性指标"},
    "unit_column": {"unit", "units", "单位"},
    "target_column": {"target", "靶点"},
    "assay_column": {"assay", "assayname", "实验", "实验方法"},
    "cell_line_column": {"cellline", "细胞系"},
    "duration_column": {"duration", "treatmentduration", "处理时长"},
    "source_page_column": {"sourcepage", "pdfpage", "原文页码", "来源页码"},
}
_PROPERTIES = {
    "molecular_weight": ({"molecularweight", "mw", "分子量"}, {"g/mol", "da"}),
    "logP": ({"logp", "clogp"}, set()),
    "tpsa": ({"tpsa", "topologicalpolarsurfacearea"}, {"a2", "å2", "angstrom2"}),
    "hydrogen_bond_donors": ({"hydrogenbonddonors", "hbd"}, set()),
    "hydrogen_bond_acceptors": ({"hydrogenbondacceptors", "hba"}, set()),
    "Solubility_AqSolDB": ({"solubilityaqsoldb", "logs"}, {"logmol/l", "logm"}),
}


def normalized(header: str) -> str:
    return re.sub(r"[\s_-]", "", unicodedata.normalize("NFKC", header).casefold())


def property_header(header: str, names: set[str], units: set[str]) -> bool:
    text = unicodedata.normalize("NFKC", header)
    suffix = re.fullmatch(r"(.+?)\s*\(([^()]+)\)\s*", text)
    if suffix:
        return normalized(suffix[1]) in names and normalized(suffix[2]) in units
    return normalized(text) in names


def activity_header(header: str) -> bool:
    text = unicodedata.normalize("NFKC", header)
    if normalized(text) in {"activity", "活性", "活性值"}:
        return True
    if numeric_direction(text, None, None)[0] != "unknown":
        return True
    matches = list(METRIC.finditer(text))
    return len(matches) == 1 and normalized(matches[0].group()) not in {
        "f",
        "cl",
        "dose",
        "pvalue",
    }


def mapping_defaults(headers: list[str]):
    """Raw columns only, deterministic across row values, language and ordering."""
    ambiguous = []

    def unique(role: str, candidates: list[str]) -> str | None:
        if len(candidates) > 1:
            ambiguous.append(role)
        return candidates[0] if len(candidates) == 1 else None

    def named(role: str, names: set[str]) -> str | None:
        return unique(
            role, [header for header in headers if normalized(header) in names]
        )

    preferred = [header for header in headers if normalized(header) in _PREFERRED_ID]
    native = native_headers(headers)
    identity = (
        ("identifier_label" if "identifier_label" in headers else "compound_id")
        if native
        else (unique("id_column", preferred) if preferred else named("id_column", _ID))
    )
    smiles = named("smiles_column", _SMILES)
    columns = {
        role: column
        for role, names in _COLUMNS.items()
        if (column := named(role, names)) is not None
    }
    if native and "activity_page" in headers:
        columns["source_page_column"] = "activity_page"
    properties = {
        role: column
        for role, (names, units) in _PROPERTIES.items()
        if (
            column := unique(
                role,
                [header for header in headers if property_header(header, names, units)],
            )
        )
        is not None
    }
    predictions = {}
    for key in LEAD_ENDPOINTS:
        names = {
            normalized(prefix + key)
            for prefix in ("predicted ", "prediction ", "admet ")
        }
        column = named(key, names)
        if column:
            predictions[key] = column
    reserved = {
        identity,
        smiles,
        *columns.values(),
        *properties.values(),
        *predictions.values(),
    }
    if "metric_column" in columns:
        value = named("activity_columns", _VALUE)
        activities = [value] if value and value not in reserved else []
    else:
        activities = [
            header
            for header in headers
            if header not in reserved and activity_header(header)
        ]
    if len(activities) > 64:
        # Ask for an explicit bounded subset, never silently choose the first 64.
        ambiguous.append("activity_columns")
        activities = []
    return (
        identity,
        smiles,
        activities,
        CSVMappingDefaults(
            columns=columns,
            property_columns=properties,
            prediction_columns=predictions,
            ambiguous_roles=ambiguous,
        ),
    )
