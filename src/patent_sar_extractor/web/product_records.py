"""Product view over the source ledger; never a new scientific role classifier."""

from patent_sar_extractor.core.cpd_filter import is_intermediate

from .models import Compound

_UNPROVED_STRUCTURE = frozenset(
    {
        "unassociated_structure",
        "structure_number_unconfirmed",
        "ambiguous_binding",
        "structure_unmatched",
        "structure_not_generated",
        "structure_generation_failed",
    }
)


def is_numbered_product(row: Compound) -> bool:
    """Preserve numbered product review even when activity/chemistry is missing.

    Original ownership is checked by the source catalogue, not inferred here
    from a drawing, a model, user rename, molecular size or an I-prefix. Raw
    unknown/intermediate observations stay in their original source ledger.
    """
    return bool(
        row.structure_id
        and row.record_kind != "activity_only"
        and not row.id.startswith("source-structure:")
        and not _UNPROVED_STRUCTURE.intersection(row.flags)
        and not is_intermediate(
            {
                "cpd": row.source.source_label,
                "cpd_id": row.id,
                "label": row.display_id,
            }
        )
    )
