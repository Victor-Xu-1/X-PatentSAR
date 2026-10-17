"""Unruled columns join the existing original-cell owner and artifact writer."""

from dataclasses import dataclass

from .activity_header_evidence import proof_id
from .numbered_structure_models import NumberedTableIssue
from .source_document import document_sha256
from .source_geometry import SourceTokens, native_region
from .source_window_chunks import observe_source_window
from .structure_table_headers import possible_structure_header, structure_column_pairs
from .table_cells import read_cell
from .unruled_structure_headers import (
    header_windows,
    nominate_unruled_headers,
    observe_unruled_header,
)
from .unruled_structure_layout import pair_evidence, region_plan
from .unruled_structure_sources import label_windows


@dataclass(frozen=True)
class UnruledTableBinding:
    label: str
    structure: dict
    proof: dict

    def evidence(self):
        return self.proof


def observe_unruled_tables(
    doc, structures, pages, grids_for_page, tokens_for_page, *, page_texts=None
):
    bindings, sections, issues, protected, recognized, observed = (
        [],
        [],
        [],
        set(),
        set(),
        set(),
    )
    original_sha = None
    by_page = {}
    for structure in structures:
        by_page.setdefault(structure["page_no"] - 1, []).append(structure)
    for page_index in sorted(set(pages)):
        if type(page_index) is not int or not 0 <= page_index < len(doc):
            continue
        page = doc[page_index]
        # Legacy boxed-cell adapters cannot prove a new original page layout.
        if not callable(getattr(page, "get_image_info", None)):
            continue
        # Actual diagram pages always receive a source inspection. For pages
        # without detected diagrams, complete original page-text observations
        # nominate missing-structure tables without launching coordinate OCR on
        # unrelated prose. Hints cannot authorize or suppress a known diagram.
        if (
            page_index not in by_page
            and page_texts is not None
            and not possible_structure_header(page_texts[page_index])
        ):
            continue
        tokens = tokens_for_page(page)
        if not isinstance(tokens, SourceTokens):
            continue
        size = [page.rect.width, page.rect.height]
        physical = grids_for_page(page)
        nominees = [
            groups
            for groups in nominate_unruled_headers(tokens, size)
            if not any(
                grid["xs"][0] <= groups[0]["bbox"][0]
                and groups[-1]["bbox"][2] <= grid["xs"][-1]
                and grid["ys"][0]
                <= groups[0]["bbox"][1]
                < groups[0]["bbox"][3]
                <= grid["ys"][-1]
                for grid in physical
            )
        ]
        for index, groups in enumerate(nominees):
            if original_sha is None:
                original_sha = document_sha256(doc)
            header = observe_unruled_header(page, tokens, groups, original_sha)
            if header is None:
                raise ValueError(
                    "Original unruled header exceeds its observation budget"
                )
            xs, ys = header_windows(groups, size)
            bottom = (
                header_windows(nominees[index + 1], size)[1][0]
                if index + 1 < len(nominees)
                else size[1]
            )
            region = {
                "status": "observed_original_unruled_columns",
                "version": 1,
                "header_scope": header,
                "body_bottom": bottom,
                "pair_sources": [],
                "labels": [],
                "diagrams": [],
            }
            pairs = structure_column_pairs([g["text"] for g in groups])
            for pair, (identifier, _structure) in enumerate(pairs):
                window = [xs[identifier], ys[1], xs[identifier + 1], bottom]
                chunks = observe_source_window(tokens, window)
                region["pair_sources"].append({"window": window, "chunks": chunks})
                for line in label_windows(chunks, window):
                    reading = read_cell(
                        page,
                        line["window"],
                        tokens,
                        "id",
                        native_region(tokens, line["window"], False),
                    )
                    region["labels"].append(
                        {
                            "pair": pair,
                            "nomination": line,
                            "value": reading.value,
                            "observations": reading.observations,
                            "needs_review": reading.needs_review,
                        }
                    )
            available = {}
            for structure in by_page.get(page_index, []):
                box = [structure[k] for k in ("x0", "y0", "x1", "y1")]
                if (
                    box[3] > ys[1]
                    and box[1] < bottom
                    and any(
                        min(box[2], xs[s + 1]) > max(box[0], xs[s]) for _, s in pairs
                    )
                ):
                    available[str(structure["id"])] = structure
            region["diagrams"] = sorted(
                [
                    {
                        "id": identity,
                        "bbox": [item[k] for k in ("x0", "y0", "x1", "y1")],
                    }
                    for identity, item in available.items()
                ],
                key=lambda item: (item["bbox"][1], item["bbox"][0], item["id"]),
            )
            _roles, assignments, findings = region_plan(region)
            region_id = proof_id(region)
            sections.append(
                {
                    "role": "unruled_structure_region",
                    "status": region["status"],
                    "page_no": page_index + 1,
                    "region_id": region_id,
                    "source": region,
                }
            )
            recognized.add(page_index)
            protected.update(available)
            observed.update(
                label["value"] for label in region["labels"] if label["value"]
            )
            issues.extend(
                NumberedTableIssue(page_index, finding["cpd"], finding["reason"])
                for finding in findings
            )
            for label, diagram in assignments:
                proof = pair_evidence(region, region_id, label, diagram)
                bindings.append(
                    UnruledTableBinding(
                        proof["source_label"], available[proof["structure_id"]], proof
                    )
                )
    return bindings, sections, issues, protected, recognized, observed
