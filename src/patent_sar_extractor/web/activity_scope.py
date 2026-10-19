"""Project-local original context identity, not inferred experimental conditions."""

import hashlib
import json
import re
from dataclasses import dataclass

from ..core.activity_context_geometry import valid_box
from ..core.activity_text_plan import validate_text_scope
from .errors import WebError


@dataclass(frozen=True)
class ActivityScope:
    identity: str
    table: str | None
    page: int
    conditions: tuple[tuple[str, str | None], ...] = ()

    def fields(self):
        return {
            "source_scope": self.identity,
            "source_table": self.table,
            "source_context_page": self.page,
            "source_conditions": dict(self.conditions),
        }


def observed_scope(source, page, table, conditions, *, document_sha256=None):
    """Reuse original header/text origins and retain exact recorded conditions.

    Anchor validation is transport integrity, not molecular/source acceptance.
    Missing legacy anchors remain absent; no table is invented from a title.
    Raw sources and scientific values are never changed.
    """
    header, text = source.get("header_region"), source.get("text_scope")
    if header is None and text is None:
        return None
    try:
        if page is None or header is not None and text is not None:
            raise ValueError("Ambiguous original context origin")
        if text is not None:
            validate_text_scope({"kind": "text", "page_no": page, "text_scope": text})
            origin = text["origin"]
            anchor = ["text", *origin]
            first_page = origin[0]
        else:
            if (
                not isinstance(header, dict)
                or set(header) != {"page_no", "bbox"}
                or type(header["page_no"]) is not int
                or not 1 <= header["page_no"] <= page
                or not valid_box(header["bbox"])
            ):
                raise ValueError("Invalid original header origin")
            first_page = header["page_no"]
            anchor = ["grid", first_page, list(map(float, header["bbox"]))]
        space = source.get("geometry_space")
        if space not in (None, "rendered", "unrotated"):
            raise ValueError("Invalid original context coordinate frame")
        if document_sha256 is not None and (
            not isinstance(document_sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", document_sha256)
        ):
            raise ValueError("Invalid original document identity")
        packet = [document_sha256, anchor, space, table, sorted(conditions)]
        identity = hashlib.sha256(
            json.dumps(
                packet, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        return ActivityScope(identity, table, first_page, tuple(conditions))
    except (TypeError, ValueError, KeyError, OverflowError) as error:
        raise WebError(
            422, "invalid_artifact", "Activity context origin is invalid."
        ) from error


def validate_scope_edits(proposed, original, *, connection=None, project_id=None):
    """Numeric edits can retain a source; input cannot forge/reassign its origin."""
    fields = (
        "source_scope",
        "source_table",
        "source_context_page",
        "source_conditions",
        "name",
        "unit",
        "target",
        "assay",
    )

    def key(item):
        values = [
            getattr(item, name) if not isinstance(item, dict) else item.get(name)
            for name in fields
        ]
        values[3] = tuple(sorted((values[3] or {}).items()))
        return tuple(values)

    known = {key(item) for item in original}
    scoped_labels = {values[4:] for values in known if values[0] is not None}
    unresolved = {
        item.source_scope
        for item in proposed
        if item.source_scope is not None and key(item) not in known
    }
    if unresolved and connection is not None:
        # Existing original read-model cells only; a manual overlay cannot mint
        # a context that then authorizes another overlay. No model/source write.
        marks = ",".join("?" for _ in unresolved)
        from .activity_columns import MAX_ACTIVITY_COLUMNS

        columns = ",".join(
            "json_extract(a.value,'$." + field + "')" for field in fields
        )
        rows = connection.execute(
            "SELECT DISTINCT "
            + columns
            + " FROM compounds c, json_each(c.payload,'$.activities') a "
            "WHERE c.project_id=? AND json_extract(a.value,'$.source_scope') IN ("
            + marks
            + ") LIMIT ?",
            (project_id, *sorted(unresolved), MAX_ACTIVITY_COLUMNS + 1),
        )
        for index, row in enumerate(rows):
            if index >= MAX_ACTIVITY_COLUMNS:
                raise WebError(
                    422,
                    "correction_limit",
                    "Activity context lookup exceeds its bound.",
                )
            data = dict(zip(fields, row, strict=True))
            data["source_conditions"] = json.loads(data["source_conditions"] or "{}")
            known.add(key(data))
    for item in proposed:
        if (
            item.source_scope is None
            and key(item)[4:] in scoped_labels
            or (
                any(getattr(item, name) is not None for name in fields[:3])
                and (item.source_scope is None or key(item) not in known)
            )
        ):
            raise WebError(
                422,
                "correction_activity_origin",
                "Original activity context identity cannot be edited.",
            )
