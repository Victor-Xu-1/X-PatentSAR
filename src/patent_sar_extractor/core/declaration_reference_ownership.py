"""Whole original characterization grids are not unproved molecule catalogues."""

from .activity_context_geometry import grid_box, validate_grid_axes
from .activity_grid_role_proof import valid_role_scope


def characterization_owns_catalogue_title(original, page_source, regions):
    """Discharge only a catalogue-title demand, never a molecular/source gate.

    The same complete role/pixel observations still require original replay.
    Partial, conflicting, diagram-bearing or foreign frames cannot borrow a
    neighboring characterization record to hide an unknown original title.
    """
    if (
        not isinstance(original, dict)
        or not isinstance(page_source, dict)
        or original.get("role") != "unresolved"
        or original.get("unproved_title") is not True
        or original.get("unproved_nonfinal_role") is not False
        or original.get("diagrams") != []
        or type(original.get("page_no")) is not int
        or type(page_source.get("page_no")) is not int
        or original["page_no"] != page_source.get("page_no")
        or not isinstance(page_source.get("page_grids"), list)
        or not isinstance(regions, list)
    ):
        return False
    try:
        grids = [
            g for g in page_source["page_grids"] if grid_box(g) == original["bbox"]
        ]
        owners = [
            r
            for r in regions
            if isinstance(r, dict)
            and type(r.get("page_no")) is int
            and r["page_no"] == original["page_no"]
            and r.get("bbox") == original["bbox"]
        ]
        if len(grids) != 1 or len(owners) != 1:
            return False
        validate_grid_axes(grids[0], original["bbox"])
        if not valid_role_scope(owners[0]):
            return False
        role = owners[0]["role_scope"]
        return role["xs"] == grids[0]["xs"] and role["ys"] == grids[0]["ys"]
    except (KeyError, TypeError, ValueError, IndexError):
        return False
