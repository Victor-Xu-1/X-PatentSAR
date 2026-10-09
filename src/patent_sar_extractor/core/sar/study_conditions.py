"""Explicit source-anchored assay declarations; never infer missing conditions."""

from __future__ import annotations

from .contexts import REQUIRED_CONTEXT, UNKNOWN_CONTEXT
from .errors import SARInputError


def missing_condition(value):
    return value is None or value.strip().casefold() in UNKNOWN_CONTEXT


def validate_declarations(dataset, contexts, selected, declarations):
    if not declarations:
        return
    if (
        dataset["source_kind"] != "project"
        or not dataset.get("source_document_sha256")
        or not dataset.get("source_page_count")
    ):
        raise SARInputError("study_conditions_source_unknown")
    known = {context["id"]: context for context in contexts}
    ids = [declaration["context_id"] for declaration in declarations]
    if len(ids) != len(set(ids)) or not set(ids).issubset(selected):
        raise SARInputError("study_conditions_context_identity")
    for declaration in declarations:
        fields = declaration["fields"]
        if not fields or not set(fields).issubset(REQUIRED_CONTEXT):
            raise SARInputError("study_conditions_field")
        if any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 1000
            or missing_condition(value)
            for value in fields.values()
        ):
            raise SARInputError("study_conditions_value")
        if any(
            not missing_condition(known[declaration["context_id"]]["context"].get(key))
            for key in fields
        ):
            raise SARInputError("study_conditions_recorded_field")
        pages = declaration["source_pages"]
        if (
            declaration["source_document_sha256"] != dataset["source_document_sha256"]
            or not pages
            or len(pages) != len(set(pages))
            or any(
                type(page) is not int or not 1 <= page <= dataset["source_page_count"]
                for page in pages
            )
            or not declaration["note"].strip()
        ):
            raise SARInputError("study_conditions_source_identity")


def declared_observation(observation, declaration):
    if declaration is None:
        return observation
    context = dict(observation.get("context", {}))
    for key, value in declaration["fields"].items():
        if not missing_condition(context.get(key)):
            raise SARInputError("study_conditions_recorded_field")
        context[key] = value
    return {**observation, "context": context, "_sar_declared_context": True}
