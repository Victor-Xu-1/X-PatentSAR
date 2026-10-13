"""Read-only source-scope validation for older raw observations, not science.

Only unchanged pure native/scanned input may transport without another model
call. Older native+raster pages lack the required coverage and are refused.
"""

import fitz

from .source_geometry import source_layout


def preserved_source_provenance(metadata: dict) -> dict:
    keys = {"inherited_observation_contract", "source_policy_validation"}
    present = keys.intersection(metadata)
    if not present:
        return {}
    if present != keys:
        raise ValueError("Incomplete inherited raw source provenance")
    old = metadata["inherited_observation_contract"]
    if old is not None and (
        not isinstance(old, dict)
        or type(old.get("version")) is not int
        or old != {"name": "patentsar.page-ocr-observation", "version": 1}
    ):
        raise ValueError("Unknown inherited raw observation contract")
    proof = metadata["source_policy_validation"]
    if not isinstance(proof, dict) or set(proof) != {
        "policy_version",
        "checked_pages",
        "native_raster_pages",
    }:
        raise ValueError("Malformed inherited raw source validation")
    pages = proof["checked_pages"]
    if (
        type(proof["policy_version"]) is not int
        or proof["policy_version"] != 2
        or proof["native_raster_pages"] != []
        or not isinstance(pages, list)
        or len(pages) > 10000
        or any(type(p) is not int or not 0 <= p < metadata["page_count"] for p in pages)
        or sorted(set(pages)) != pages
    ):
        raise ValueError("Invalid inherited raw source validation")
    return {key: metadata[key] for key in keys}


def legacy_source_receipt(cache: dict, pdf_path: str) -> dict | None:
    pages = set()
    for name in ("page_texts", "ocr_line_map"):
        records = cache.get(name, {})
        if not isinstance(records, dict):
            return None
        for key in records:
            if (
                not isinstance(key, str)
                or not key.isascii()
                or not key.isdecimal()
                or len(key) > 5
                or key != str(int(key))
            ):
                return None
            pages.add(int(key))
    with fitz.open(pdf_path) as doc:
        if len(doc) > 10000 or any(index >= len(doc) for index in pages):
            return None
        for index in sorted(pages):
            layout = source_layout(doc[index])
            if layout.native and layout.raster_bounds is not None:
                return None
    return {
        "policy_version": 2,
        "checked_pages": sorted(pages),
        "native_raster_pages": [],
    }
