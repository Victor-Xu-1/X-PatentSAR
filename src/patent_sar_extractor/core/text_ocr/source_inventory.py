"""One bounded auxiliary-source inventory shared by binding and activity replay."""

from patent_sar_extractor.core.source_evidence_identity import proof_id

from .cell_proof import has_auxiliary_text, valid_auxiliary_cell

_MAX_ROWS = 2048
MAX_SOURCE_CELLS = 16384


def auxiliary_source_cells(sources):
    """Conserve complete packets and reject one request acquiring two outputs."""
    seen, rows = set(), {}
    for page_no, cell in sources:
        if not has_auxiliary_text(cell):
            continue
        if not valid_auxiliary_cell(cell, cell.get("render_dpi")):
            raise ValueError("Unproved auxiliary original text cell")
        if type(page_no) is not int or not 1 <= page_no <= 20000:
            raise ValueError("Missing auxiliary original page ownership")
        key = (
            page_no,
            proof_id(
                {
                    "status": "auxiliary_text_observations",
                    "packet": cell["auxiliary_text"],
                }
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        for view in cell["auxiliary_text"]["views"]:
            observations = (
                [row["observation"] for row in view["rows"]]
                if cell["auxiliary_text"]["version"] == 1
                else view["requests"]
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
