"""Identity of a complete original characterization grid and its row evidence."""

from patent_sar_extractor.artifact_nodes import MAX_ARTIFACT_BYTES

from .activity_grid_role_proof import valid_role_scope
from .composite_source_identity import composite_source_digest
from .source_evidence_identity import MAX_SOURCE_REGION_BYTES
from .source_role_fragments import validate_fragments

MAX_REGION_BYTES = MAX_ARTIFACT_BYTES
MAX_COMPONENT_BYTES = MAX_SOURCE_REGION_BYTES

# Every original cell, row, frame or context chunk remains a separately bounded
# source component. Only their validated enclosing grid is allowed to be larger.
_PARTITIONS = {
    (),
    ("role_scope",),
    ("role_scope", "native_hints"),
    ("role_scope", "observations"),
    ("role_scope", "observations", "*"),
    ("role_scope", "observations", "*", "matrix"),
    ("role_scope", "observations", "*", "cells"),
    ("row_fragments",),
    ("row_fragments", "*"),
    ("row_fragments", "*", "source_cells"),
    ("row_fragments", "*", "source_cells", "native_hints"),
    ("row_fragments", "*", "source_cells", "observations"),
    ("row_fragments", "*", "source_cells", "observations", "*"),
    ("row_fragments", "*", "source_cells", "observations", "*", "matrix"),
    ("row_fragments", "*", "source_cells", "observations", "*", "cells"),
    ("row_fragments", "*", "source_cells", "rendered_frames"),
    ("row_fragments", "*", "source_cells", "rendered_frames", "*"),
    ("fragment_context",),
    ("fragment_context", "prefix"),
    ("fragment_context", "suffix"),
}


def reference_region_id(record):
    """Validate all original cells before hashing the complete bounded region."""
    if not isinstance(record, dict) or not valid_role_scope(record):
        raise ValueError("Unproved original characterization region")
    if "grid_edges" in record:
        validate_fragments(record)
    return composite_source_digest(
        record,
        _PARTITIONS,
        maximum=MAX_REGION_BYTES,
        component_limit=MAX_COMPONENT_BYTES,
        label="characterization region",
    )
