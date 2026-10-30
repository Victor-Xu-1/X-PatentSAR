"""One bounded auxiliary-source inventory shared by binding and activity replay."""

from patent_sar_extractor.contracts import AUXILIARY_TEXT_RECOVERY_VERSION
from patent_sar_extractor.core.source_evidence_identity import proof_id

from .cell_proof import has_auxiliary_text, valid_auxiliary_cell

_MAX_ROWS = 2048
MAX_SOURCE_CELLS = 16384


def physical_text_sources(sources):
    """Expand only the explicit original-title carrier; never recurse arbitrary JSON."""
    for page_no, cell in sources:
        if isinstance(cell, dict) and cell.get("method") == "original_title_context":
            from ..title_context_source import title_context_bounds

            if (
                set(cell) != {"method", "title_context"}
                or title_context_bounds(cell["title_context"]) is None
                or cell["title_context"]["page_no"] != page_no
            ):
                raise ValueError("Malformed original title context owner")
        elif isinstance(cell, dict) and cell.get("method") == "original_title":
            from ..title_source_proof import source_title_geometry

            if (
                set(cell) != {"method", "title_source"}
                or source_title_geometry(cell["title_source"]) is None
                or cell["title_source"]["page_no"] != page_no
            ):
                raise ValueError("Malformed original title text owner")
            if cell["title_source"].get("auxiliary_title") is not None:
                yield page_no, cell
            for reading in cell["title_source"]["observations"]:
                yield page_no, reading
        else:
            yield page_no, cell


def has_auxiliary_source(cell):
    return has_auxiliary_text(cell) or bool(
        isinstance(cell, dict)
        and cell.get("method") == "original_title"
        and isinstance(cell.get("title_source"), dict)
        and cell["title_source"].get("auxiliary_title") is not None
    )


def _source_packet(cell):
    if isinstance(cell, dict) and cell.get("method") == "original_title":
        from ..title_lexical_recovery import recovered_title_observation

        if (
            set(cell) != {"method", "title_source"}
            or recovered_title_observation(cell["title_source"]) is None
        ):
            raise ValueError("Unproved auxiliary original title")
        return cell["title_source"]["auxiliary_title"]
    if not valid_auxiliary_cell(cell, cell.get("render_dpi")):
        raise ValueError("Unproved auxiliary original text cell")
    return cell["auxiliary_text"]


def replay_auxiliary_source(cell, page):
    if isinstance(cell, dict) and cell.get("method") == "original_title":
        from ..title_lexical_recovery import replay_title_lexical_recovery

        try:
            _source_packet(cell)
            replay_title_lexical_recovery(page, cell["title_source"])
            return True
        except (TypeError, ValueError, KeyError, IndexError, RuntimeError):
            return False
    from .cell_proof import replay_auxiliary_cell

    return replay_auxiliary_cell(cell, page)


def auxiliary_source_cells(sources):
    """Conserve complete packets and reject one request acquiring two outputs."""
    seen, rows = set(), {}
    for page_no, cell in physical_text_sources(sources):
        if not has_auxiliary_source(cell):
            continue
        packet = _source_packet(cell)
        if type(page_no) is not int or not 1 <= page_no <= 20000:
            raise ValueError("Missing auxiliary original page ownership")
        key = (
            page_no,
            proof_id(
                {
                    "status": "auxiliary_text_observations",
                    "packet": packet,
                }
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        for view in packet["views"]:
            observations = (
                [row["observation"] for row in view["rows"]]
                if packet["version"] == 1
                else (
                    [
                        observed
                        for row in view["requests"]
                        for observed in row["observations"]
                    ]
                    if packet["version"] in (3, AUXILIARY_TEXT_RECOVERY_VERSION)
                    else view["requests"]
                )
            )
            for row in observations:
                observed = {k: v for k, v in row.items() if k != "cache_hit"}
                identity = observed["model_fingerprint"], observed["id"]
                if identity in rows and rows[identity] != observed:
                    raise ValueError(
                        "One auxiliary observation identity has conflicting outputs"
                    )
                rows[identity] = observed
        if len(rows) > _MAX_ROWS or len(seen) > MAX_SOURCE_CELLS:
            raise ValueError(
                "Auxiliary original row inventory exceeds its session bound"
            )
        yield page_no, cell
