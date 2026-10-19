"""Revalidate original text plans and exact row/cell/context conservation."""

from collections import defaultdict

from .activity_context_values import SCIENTIFIC_CONTEXT_FIELDS
from .activity_headers import context_from_text
from .activity_text_plan import scope_descriptor, source_plan, validate_text_scope


def _get(row, key, default=None):
    return (
        row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)
    )


def text_source_errors(pages, regions, rows):
    expected = source_plan(dict(pages))
    scoped = [r for r in regions if r.get("text_scope")]
    if not expected and not scoped and rows is None:
        return []
    if rows is None:
        return ["Original text sources need their current row observations."]
    observed, errors = defaultdict(list), []
    count = 0
    for row in rows:
        sources = _get(row, "activity_sources", [])
        if not isinstance(sources, list) or len(sources) > 500:
            raise ValueError("Malformed original text source packets")
        count += len(sources)
        if count > 100000:
            raise ValueError("Original text source packets exceed their bound")
        for source in sources:
            if not isinstance(source, dict):
                raise TypeError("Malformed original text source row")
            scope = source.get("text_scope")
            if scope is None:
                if _get(row, "source") == "observed_text_table":
                    errors.append("An original text row has no current source scope.")
                continue
            if (
                not isinstance(scope, dict)
                or not isinstance(scope.get("span"), list)
                or len(scope["span"]) != 2
            ):
                raise ValueError("Malformed original text row scope")
            if type(source.get("page_no")) is not int:
                raise ValueError("Malformed original text source page")
            validate_text_scope(
                {"kind": "text", "page_no": source["page_no"], "text_scope": scope}
            )
            observed[(source["page_no"], *scope["span"])].append((row, source))
    indexed = {(r["page_no"], *r["text_scope"]["span"]): r for r in scoped}
    keys = {tuple(item["key"]) for item in expected}
    if set(indexed) != keys or set(observed) - keys:
        raise ValueError(
            "Original text scopes do not match their recorded observations"
        )
    for item in expected:
        key = tuple(item["key"])
        region = indexed[key]
        context = item.get("context") or context_from_text(item["caption"])
        if (
            region["text_scope"] != scope_descriptor(item)
            or region["table_id"] != context.table_id
            or region["header"] != item["header"][:1024]
            or region["row_count"] != len(item["rows"])
            or region["status"] != item["status"]
        ):
            raise ValueError("Text inventory differs from the original source plan")
        originals = {r.activity_sources[0]["row"]: r for r in item["rows"]}
        packets = observed[key]
        positions = [s.get("row") for _, s in packets]
        if (
            len(packets) != len(originals)
            or any(type(p) is not int for p in positions)
            or len(set(positions)) != len(positions)
        ):
            errors.append(f"Original text row population is incomplete p{key[0]}.")
            continue
        for row, source in packets:
            original = originals.get(source["row"])
            if original is None:
                errors.append("An original text row position has no source owner.")
                continue
            proof = original.activity_sources[0]
            if (
                source.get("text_scope") != scope_descriptor(item)
                or _get(row, "cpd") != original.cpd
                or original.needs_review
                and not _get(row, "needs_review", False)
                or any(
                    source.get(k) != proof.get(k)
                    for k in (
                        "table_id",
                        "raw_caption",
                        "body_text",
                        "raw_context",
                        *SCIENTIFIC_CONTEXT_FIELDS,
                        "raw_header",
                        "cells",
                        "legend",
                        "legend_issues",
                    )
                )
                or any(
                    _get(row, "activity_values", {}).get(k) != v
                    for k, v in original.activity_values.items()
                )
            ):
                errors.append(f"Unproved original text row, context or cell p{key[0]}.")
    return errors
