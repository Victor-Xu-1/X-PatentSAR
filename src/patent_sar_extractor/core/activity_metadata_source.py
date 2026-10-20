"""Original metadata blanks reuse the shared closed-grid pixel proof."""

from .activity_metadata import metadata_role
from .cell_empty_proof import observe_empty_grid_cell


def observe_metadata_blank(page, cell, kind):
    if metadata_role(cell.get("raw_header")) != kind:
        raise ValueError("A metadata source requires its original header role")
    if cell["value"].strip():
        return cell
    reading = observe_empty_grid_cell(page, cell["bbox"])
    if reading is None:
        return cell
    return {**cell, "observations": [*cell["observations"], reading]}
