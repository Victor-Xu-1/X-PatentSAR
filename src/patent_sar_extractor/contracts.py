"""Authoritative product, pipeline, ruleset, schema, and cache identifiers."""

from __future__ import annotations

from typing import Final


PRODUCT_NAME: Final = "X-PatentSAR"
DISTRIBUTION_NAME: Final = "x-patentsar"
COMMAND_NAME: Final = "x-patentsar"
__version__: Final = "0.1.0"

WEB_API_SCHEMA: Final = "patentsar.web-api"
WEB_API_SCHEMA_VERSION: Final = 1

PIPELINE_CONTRACT_NAME: Final = "patentsar.activity-led"
PIPELINE_CONTRACT_VERSION: Final = "2.0.0"

RULESET_NAME: Final = "patentsar.accuracy-first"
RULESET_VERSION: Final = "2.0.2"

RUN_SUMMARY_SCHEMA: Final = "patentsar.run-summary"
RUN_SUMMARY_SCHEMA_VERSION: Final = 1
STEP_MANIFEST_SCHEMA: Final = "patentsar.step-manifest"
STEP_MANIFEST_SCHEMA_VERSION: Final = 1
PAGE_CLASSIFICATION_SCHEMA: Final = "patentsar.page-classification"
PAGE_CLASSIFICATION_SCHEMA_VERSION: Final = 2
REVIEW_EXCERPT_METADATA_SCHEMA: Final = "patentsar.review-excerpt-metadata"
REVIEW_EXCERPT_METADATA_SCHEMA_VERSION: Final = 1
ACTIVITY_SCHEMA: Final = "patentsar.activity"
ACTIVITY_SCHEMA_VERSION: Final = 1
ACTIVITY_EXTRACTOR_VERSION: Final = "2"
STRUCTURE_LOCATOR_VERSION: Final = "3"
STRUCTURE_WORKER_VERSION: Final = "3"
STRUCTURE_BINDER_VERSION: Final = "3"
OCSR_OBSERVATION_VERSION: Final = "2"
STRUCTURE_LOCATION_SCHEMA: Final = "patentsar.structure-location"
STRUCTURE_LOCATION_SCHEMA_VERSION: Final = 1
STRUCTURES_SCHEMA: Final = "patentsar.structures"
STRUCTURES_SCHEMA_VERSION: Final = 1
BINDINGS_SCHEMA: Final = "patentsar.bindings"
BINDINGS_SCHEMA_VERSION: Final = 2
SMILES_SCHEMA: Final = "patentsar.smiles"
SMILES_SCHEMA_VERSION: Final = 1
QA_REPORT_SCHEMA: Final = "patentsar.qa-report"
QA_REPORT_SCHEMA_VERSION: Final = 2
LLM_QA_REPORT_SCHEMA: Final = "patentsar.llm-qa-report"
LLM_QA_REPORT_SCHEMA_VERSION: Final = 1
HEALTH_REPORT_SCHEMA: Final = "patentsar.health-report"
HEALTH_REPORT_SCHEMA_VERSION: Final = 1
FAILURE_MARKER_SCHEMA: Final = "patentsar.failure-marker"
FAILURE_MARKER_SCHEMA_VERSION: Final = 1
PAGE_OCR_CACHE_SCHEMA: Final = "patentsar.page-ocr-cache"
PAGE_OCR_CACHE_SCHEMA_VERSION: Final = 1
PAGE_OCR_OBSERVATION_SCHEMA: Final = "patentsar.page-ocr-observation"
PAGE_OCR_OBSERVATION_VERSION: Final = 1
# This compatibility is for raw observations only, never derived/accepted data.
# 2.0.0 lacks coherent scanned-page coordinates and is intentionally excluded.
PAGE_OCR_COMPATIBLE_RULESETS: Final = ((RULESET_NAME, "2.0.1"), (RULESET_NAME, RULESET_VERSION))
VISIBLE_LABEL_CACHE_SCHEMA: Final = "patentsar.visible-label-cache"
VISIBLE_LABEL_CACHE_SCHEMA_VERSION: Final = 1


def schema_ref(name: str, version: int) -> dict[str, object]:
    return {"name": name, "version": version}


def product_ref() -> dict[str, str]:
    return {"name": PRODUCT_NAME, "version": __version__}


def pipeline_contract_ref() -> dict[str, str]:
    return {"name": PIPELINE_CONTRACT_NAME, "version": PIPELINE_CONTRACT_VERSION}


def ruleset_ref() -> dict[str, str]:
    return {"name": RULESET_NAME, "version": RULESET_VERSION}


def artifact_identity(schema_name: str, schema_version: int) -> dict[str, object]:
    """Return the common identity envelope for versioned JSON artifacts."""

    return {
        "schema": schema_ref(schema_name, schema_version),
        "product": product_ref(),
        "pipeline_contract": pipeline_contract_ref(),
        "ruleset": ruleset_ref(),
    }


def artifact_identity_matches(payload: object, schema_name: str, schema_version: int) -> bool:
    """Return whether a payload has the exact current identity envelope."""

    if not isinstance(payload, dict):
        return False
    expected = artifact_identity(schema_name, schema_version)
    return all(payload.get(key) == value for key, value in expected.items())
