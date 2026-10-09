"""Authoritative product, pipeline, ruleset, schema, and cache identifiers."""

from __future__ import annotations

import re
from typing import Final

PRODUCT_NAME: Final = "X-PatentSAR"
DISTRIBUTION_NAME: Final = "x-patentsar"
COMMAND_NAME: Final = "x-patentsar"
__version__: Final = "0.1.15"

WEB_API_SCHEMA: Final = "patentsar.web-api"
WEB_API_SCHEMA_VERSION: Final = 1

# Independent research domain; never changes the formal extraction stage order.
SAR_ENGINE_NAME: Final = "patentsar.strict-reference-sar"
SAR_ENGINE_VERSION: Final = 3
SAR_DATABASE_VERSION: Final = 2
SAR_REPORT_SCHEMA: Final = "patentsar.reference-sar-report"
SAR_REPORT_SCHEMA_VERSION: Final = 1
SAR_STUDY_REPORT_SCHEMA: Final = "patentsar.sar-study-report"
SAR_STUDY_REPORT_SCHEMA_VERSION: Final = 1

PIPELINE_CONTRACT_NAME: Final = "patentsar.structure-led"
PIPELINE_CONTRACT_VERSION: Final = "3.0.0"
CORE_STAGE_ORDER: Final = (
    "classify",
    "locate",
    "structures",
    "bind",
    "activity",
    "smiles",
    "final",
    "qa",
)

RULESET_NAME: Final = "patentsar.accuracy-first"
RULESET_VERSION: Final = "2.1.1"

RUN_SUMMARY_SCHEMA: Final = "patentsar.run-summary"
RUN_SUMMARY_SCHEMA_VERSION: Final = 1
STAGE_PROGRESS_SCHEMA: Final = "patentsar.stage-progress"
STAGE_PROGRESS_SCHEMA_VERSION: Final = 1
STEP_MANIFEST_SCHEMA: Final = "patentsar.step-manifest"
STEP_MANIFEST_SCHEMA_VERSION: Final = 1
PAGE_CLASSIFICATION_SCHEMA: Final = "patentsar.page-classification"
PAGE_CLASSIFICATION_SCHEMA_VERSION: Final = 2
PAGE_CLASSIFIER_VERSION: Final = "2"
REVIEW_EXCERPT_METADATA_SCHEMA: Final = "patentsar.review-excerpt-metadata"
REVIEW_EXCERPT_METADATA_SCHEMA_VERSION: Final = 1
ACTIVITY_SCHEMA: Final = "patentsar.activity"
ACTIVITY_SCHEMA_VERSION: Final = 1
ACTIVITY_EXTRACTOR_VERSION: Final = "7"
ACTIVITY_COVERAGE_SCHEMA: Final = "patentsar.activity-coverage"
ACTIVITY_COVERAGE_SCHEMA_VERSION: Final = 1
STRUCTURE_LOCATOR_VERSION: Final = "5"
STRUCTURE_WORKER_VERSION: Final = "5"
SEGMENTATION_WINDOW_SCHEMA: Final = "patentsar.segmentation-window"
SEGMENTATION_WINDOW_SCHEMA_VERSION: Final = 2
SEGMENTATION_INPUT_FINGERPRINT_FILE: Final = "input_fingerprint.json"
STRUCTURE_BINDER_VERSION: Final = "8"
OCSR_OBSERVATION_VERSION: Final = "2"
STEREO_EVIDENCE_VERSION: Final = 3
DECIMER_ADAPTER_VERSION: Final = "1"
STRUCTURE_LOCATION_SCHEMA: Final = "patentsar.structure-location"
STRUCTURE_LOCATION_SCHEMA_VERSION: Final = 1
STRUCTURES_SCHEMA: Final = "patentsar.structures"
STRUCTURES_SCHEMA_VERSION: Final = 1
BINDINGS_SCHEMA: Final = "patentsar.bindings"
BINDINGS_SCHEMA_VERSION: Final = 2
COMPOUND_CATALOG_SCHEMA: Final = "patentsar.compound-catalog"
COMPOUND_CATALOG_SCHEMA_VERSION: Final = 1
SMILES_SCHEMA: Final = "patentsar.smiles"
SMILES_SCHEMA_VERSION: Final = 2
QA_REPORT_SCHEMA: Final = "patentsar.qa-report"
QA_REPORT_SCHEMA_VERSION: Final = 4
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
PAGE_OCR_COMPATIBLE_RULESETS: Final = (
    (RULESET_NAME, "2.0.1"),
    (RULESET_NAME, "2.0.2"),
    (RULESET_NAME, "2.0.3"),
    (RULESET_NAME, "2.0.4"),
    (RULESET_NAME, "2.1.0"),
    (RULESET_NAME, RULESET_VERSION),
)
# Supported producers of the unchanged raw observation format, not permission
# to reuse any classifications, associations, chemistry or acceptance.
PAGE_OCR_COMPATIBLE_PIPELINES: Final = (
    ("patentsar.activity-led", "2.0.0"),
    (PIPELINE_CONTRACT_NAME, PIPELINE_CONTRACT_VERSION),
)
VISIBLE_LABEL_CACHE_SCHEMA: Final = "patentsar.visible-label-cache"
VISIBLE_LABEL_CACHE_SCHEMA_VERSION: Final = 1
VISIBLE_LABEL_OBSERVATION_VERSION: Final = 8


def schema_ref(name: str, version: int) -> dict[str, object]:
    return {"name": name, "version": version}


def product_ref() -> dict[str, str]:
    return {"name": PRODUCT_NAME, "version": __version__}


def product_identity_matches(payload: object) -> bool:
    """Check producer identity, not scientific compatibility via release labels.

    Product releases count merged PRs. Scientific changes instead invalidate
    their explicit pipeline, ruleset, schema and implementation epochs.
    """
    return (
        isinstance(payload, dict)
        and set(payload) == {"name", "version"}
        and payload.get("name") == PRODUCT_NAME
        and isinstance(payload.get("version"), str)
        and len(payload["version"]) <= 32
        and re.fullmatch(
            r"(?:0|[1-9][0-9]*)\.[0-9]\.(?:0|[1-9][0-9]?)", payload["version"]
        )
        is not None
    )


def release_compatible_record(actual: object, expected: dict[str, object]) -> bool:
    """Compare a complete identity/fingerprint except its producer release label.

    No keys are dropped or mutated. Missing/foreign/malformed producers and
    every other changed field still fail closed.
    """
    return (
        isinstance(actual, dict)
        and actual.keys() == expected.keys()
        and product_identity_matches(actual.get("product"))
        and product_identity_matches(expected.get("product"))
        and all(
            actual[key] == value for key, value in expected.items() if key != "product"
        )
    )


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


def artifact_identity_matches(
    payload: object, schema_name: str, schema_version: int
) -> bool:
    """Check current scientific contracts while retaining producer provenance."""

    if not isinstance(payload, dict):
        return False
    expected = artifact_identity(schema_name, schema_version)
    return release_compatible_record(
        {key: payload.get(key) for key in expected}, expected
    )
