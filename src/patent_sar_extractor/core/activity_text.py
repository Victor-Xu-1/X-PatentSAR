"""One original text coordinator; plan/row proof share pure lower authorities."""

from .activity_coverage import source_record
from .activity_headers import context_from_text
from .activity_models import ParsedActivity
from .activity_text_plan import scope_descriptor, source_plan
from .activity_text_rows import parse_segment

__all__ = ["extract_text_tables", "parse_segment"]


def extract_text_tables(
    pages, text_map, *, page_count=None, page_reader=None, blocked_pages=()
):
    result = ParsedActivity()
    result.text_pages = {
        str(p + 1): str(text_map.get(str(p), "") or "") for p in sorted(set(pages))
    }
    plan = source_plan(
        result.text_pages,
        page_count=page_count,
        page_reader=page_reader,
        blocked={p + 1 for p in blocked_pages},
    )
    for item in plan:
        page_no, _, _ = item["key"]
        scope = scope_descriptor(item)
        rows = item["rows"]
        context = item.get("context") or context_from_text(item["caption"])
        for row in rows:
            for source in row.activity_sources:
                source["text_scope"] = scope
        result.rows.extend(rows)
        if rows:
            result.owned_pages.add(page_no - 1)
            result.headers.extend(key for row in rows for key in row.activity_values)
        result.tables.append(
            {
                "table_id": context.table_id,
                "pages": [page_no - 1],
                "heading_page_idx": page_no - 1,
                "heading_text": item["caption"],
            }
        )
        result.coverage.append(
            source_record(
                page_no,
                "text",
                None,
                context.table_id,
                item["header"],
                item["status"],
                "declared_text"
                if rows
                else "original_header_only"
                if item["status"] == "header"
                else "no_original_rows",
                len(rows),
                text_scope=scope,
            )
        )
    return result
