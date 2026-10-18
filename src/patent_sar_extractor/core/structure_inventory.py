"""One bounded page-observation receipt; detection is not chemical acceptance."""

from collections import Counter

from patent_sar_extractor.contracts import (
    STRUCTURE_INVENTORY_SCHEMA,
    STRUCTURE_INVENTORY_SCHEMA_VERSION,
    schema_ref,
)

MAX_PAGES = 10000
MAX_CANDIDATES = 100000


def inventory_packet(page_count: int, pages: list[dict]) -> dict:
    packet = {
        "schema": schema_ref(
            STRUCTURE_INVENTORY_SCHEMA, STRUCTURE_INVENTORY_SCHEMA_VERSION
        ),
        "page_count": page_count,
        "pages": pages,
    }
    _validate_packet(packet)
    return packet


def _validate_packet(packet: object) -> None:
    if (
        not isinstance(packet, dict)
        or set(packet) != {"schema", "page_count", "pages"}
        or not isinstance(packet["schema"], dict)
        or type(packet["schema"].get("version")) is not int
        or packet["schema"]
        != schema_ref(STRUCTURE_INVENTORY_SCHEMA, STRUCTURE_INVENTORY_SCHEMA_VERSION)
        or type(packet["page_count"]) is not int
        or not 1 <= packet["page_count"] <= MAX_PAGES
        or not isinstance(packet["pages"], list)
        or len(packet["pages"]) > packet["page_count"]
    ):
        raise ValueError("Missing or malformed structure page inventory")
    seen = set()
    for row in packet["pages"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"page_no", "status", "scope", "candidates"}
            or type(row["page_no"]) is not int
            or not 1 <= row["page_no"] <= packet["page_count"]
            or row["page_no"] in seen
            or row["status"] not in {"detected", "failed"}
            or row["scope"] not in {"full_page", "region"}
            or type(row["candidates"]) is not int
            or not 0 <= row["candidates"] <= MAX_CANDIDATES
        ):
            raise ValueError("Invalid or duplicate structure page observation")
        seen.add(row["page_no"])


def validate_structure_inventory(
    payload: dict,
    *,
    expected_pages: list[int] | None = None,
    page_count: int | None = None,
    full_document: bool = False,
    require_full_page: bool = True,
) -> dict:
    """Require conserved crops and successful coverage, including zero-crop pages.

    Chunk checks prove exactly their requested subset; only full_document proves
    processing every original page. A detector's zero is never proof that the
    source contains no chemistry, and no missing page is treated as zero.
    """
    if not isinstance(payload, dict):
        raise TypeError("Malformed structure metadata")
    packet = payload.get("source_inventory")
    _validate_packet(packet)
    count = packet["page_count"]
    if page_count is not None and (type(page_count) is not int or page_count != count):
        raise ValueError("Structure inventory belongs to a different page count")
    rows = packet["pages"]
    observed = {r["page_no"] - 1 for r in rows}
    if expected_pages is not None and (
        not isinstance(expected_pages, list)
        or any(type(p) is not int or not 0 <= p < count for p in expected_pages)
        or len(set(expected_pages)) != len(expected_pages)
        or set(expected_pages) != observed
    ):
        raise ValueError("Structure inventory does not cover the exact requested pages")
    if full_document and observed != set(range(count)):
        raise ValueError("Structure inventory does not cover every original page")
    if any(r["status"] != "detected" for r in rows) or payload.get("failed_pages"):
        raise ValueError("Structure page detection has recorded failures")
    if require_full_page and any(r["scope"] != "full_page" for r in rows):
        raise ValueError("Partial-region detection cannot prove full-page coverage")
    structures = payload.get("structures")
    if (
        not isinstance(structures, list)
        or len(structures) > MAX_CANDIDATES
        or type(payload.get("total_structures")) is not int
        or payload["total_structures"] != len(structures)
    ):
        raise ValueError("Structure candidate count is not conserved")
    ids, counts = set(), Counter()
    for structure in structures:
        if (
            not isinstance(structure, dict)
            or type(structure.get("page_no")) is not int
            or structure["page_no"] - 1 not in observed
            or not isinstance(structure.get("structure_id"), str)
            or not 1 <= len(structure["structure_id"]) <= 128
            or structure["structure_id"] in ids
        ):
            raise ValueError("Structure candidate has invalid source-page ownership")
        ids.add(structure["structure_id"])
        counts[structure["page_no"]] += 1
    if any(counts[row["page_no"]] != row["candidates"] for row in rows):
        raise ValueError("Structure page candidate count is not conserved")
    return packet


def structure_coverage_errors(payload: dict, page_count: int | None) -> list[str]:
    """QA reports absence/failure rather than rewriting an old inventory."""
    try:
        if type(page_count) is not int or not 1 <= page_count <= MAX_PAGES:
            raise ValueError("Original document page count is missing")
        validate_structure_inventory(payload, page_count=page_count, full_document=True)
    except (ValueError, TypeError, KeyError) as exc:
        return [f"Original structure-page coverage is unproved: {exc}."]
    return []
