"""Existing closed-cell capture/replay for caption locator-role references."""

from .caption_label_roles import ROLE, caption_label_reference
from .caption_locator_proof import locator_candidate, valid_locator_scope
from .cell_frame_proof import inside_box
from .heading_cell_source import observe_cell_source
from .heading_source_geometry import MAX_HEADING_HEIGHT


def observe_caption_locator(page, line, index, *, grids_for_page=None):
    # No page source, no geometric guess and no additional original rendering.
    if not locator_candidate(line) or not any(
        source.get("cell_bbox") and inside_box(line.get("bbox"), source["cell_bbox"])
        for source in index.get(page.number + 1, {}).values()
    ):
        return None
    if grids_for_page is None:
        from .table_geometry import detect_ruled_table_regions

        grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
    else:
        grids = grids_for_page(page)
    source = observe_cell_source(page, line["bbox"], grids, MAX_HEADING_HEIGHT)
    return (
        caption_label_reference(
            line,
            page.number + 1,
            index,
            physical_source=source,
            page_size=[page.rect.width, page.rect.height],
        )
        if source is not None
        else None
    )


def caption_locator_sources(payload):
    """Explicit ledger owners only; no recursive artifact or path search."""
    from .binding_source_references import MAX_SOURCE_SECTIONS

    sections = payload.get("source_sections", [])
    if not isinstance(sections, list) or len(sections) > MAX_SOURCE_SECTIONS:
        raise ValueError("Malformed caption locator-source inventory")
    for section in sections:
        if not isinstance(section, dict):
            raise TypeError("Malformed caption locator-source owner")
        if section.get("role") == ROLE and "physical_source" in section:
            line = {
                "text": section.get("line_text"),
                "source": section.get("line_source"),
                "geometry_space": section.get("geometry_space"),
                "bbox": section.get("bbox"),
            }
            if not valid_locator_scope(
                section["physical_source"], line, section.get("page_size")
            ):
                raise ValueError("Unproved caption locator-source ownership")
            yield section


def original_caption_locator_errors(document, sources):
    """No OCR: rederive the same full closed source from the actual original."""
    from .table_geometry import detect_ruled_table_regions

    grids, cells = {}, {}
    try:
        for source in sources:
            line = {
                "text": source.get("line_text"),
                "source": source.get("line_source"),
                "geometry_space": source.get("geometry_space"),
                "bbox": source.get("bbox"),
            }
            if not valid_locator_scope(
                source.get("physical_source"), line, source.get("page_size")
            ):
                return ["Original caption locator source is unproved."]
            number = source["page_no"]
            if type(number) is not int or not 1 <= number <= len(document):
                return ["Original caption locator page is unavailable."]
            page = document[number - 1]
            if source["page_size"] != [page.rect.width, page.rect.height]:
                return ["Original caption locator geometry differs."]
            if number not in grids:
                grids[number] = detect_ruled_table_regions(
                    page, dpi=240, minimum_columns=1
                )
            key = number, tuple(source["bbox"])
            if key not in cells:
                cells[key] = observe_cell_source(
                    page, source["bbox"], grids[number], MAX_HEADING_HEIGHT
                )
            actual, saved = cells[key], source["physical_source"]
            if (
                actual is None
                or actual["cell"] != saved["cell"]
                or actual["pixels"] != saved["pixels"]
            ):
                return ["Caption locator differs from its actual original closed cell."]
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        IndexError,
        OverflowError,
    ):
        return ["Original caption locator replay is unavailable."]
    return []
