"""Bounded streaming identity for complete, already validated page evidence."""

from patent_sar_extractor.artifact_nodes import MAX_ARTIFACT_BYTES

from .caption_role_identity import caption_ancestry_partitions
from .composite_source_identity import composite_source_digest
from .source_evidence_identity import MAX_SOURCE_REGION_BYTES

MAX_PAGE_BYTES = MAX_ARTIFACT_BYTES
MAX_COMPONENT_BYTES = MAX_SOURCE_REGION_BYTES
PAGE_COMPONENTS = (
    "page_context",
    "page_diagrams",
    "page_grids",
    "catalogue_scopes",
    "logical_columns",
    "continued_columns",
)


def page_source_digest(source):
    """Bind every page field after its original schema and coverage are validated.

    Each context chunk, original grid, diagram and local catalogue source keeps
    the established one-MiB region budget. Validated prior-page ancestry is an
    inventory of those bounded facts. The full page has an independent finite
    32-MiB budget matching artifact transport. The emitted bytes match the old
    canonical JSON digest exactly, but are streamed without a full-page copy.
    """
    if not isinstance(source, dict):
        raise TypeError("Malformed original declaration page")
    partitions = {(), *((name,) for name in PAGE_COMPONENTS)}
    for scope in source.get("catalogue_scopes", []):
        partitions.update(
            caption_ancestry_partitions(
                scope,
                ("catalogue_scopes", "*"),
                component_limit=MAX_COMPONENT_BYTES,
            )
        )
    return composite_source_digest(
        source,
        partitions,
        maximum=MAX_PAGE_BYTES,
        component_limit=MAX_COMPONENT_BYTES,
        label="declaration page",
    )
