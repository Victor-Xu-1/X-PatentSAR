"""Call-local original page inventory for the single heading scope/replay policy."""

from collections import defaultdict

from .heading_column_captions import capture_caption_frames, column_caption_boxes
from .heading_column_sources import COLUMN_SOURCE_ROLES, independent_columns
from .heading_declaration_scope import (
    MAX_DECLARATION_PAGES,
    MAX_DECLARATION_STRUCTURES,
    _page_valid,
    declaration_candidates,
    declaration_window,
)
from .heading_line_windows import heading_line_windows
from .heading_page_columns import capture_column_cells, later_page_columns
from .heading_panel_scope import observe_panel
from .source_evidence_identity import SourceEvidenceLimit, proof_id


class HeadingDeclarationIndex:
    """Shared original pages; no new store, OCR, queue or identifier guess."""

    def __init__(
        self,
        doc,
        structures,
        lines_for_page,
        original_sha,
        *,
        source_sections=(),
        source_cells=(),
        grids_for_page=None,
    ):
        self.doc, self.lines_for_page, self.original_sha = (
            doc,
            lines_for_page,
            original_sha,
        )
        self.structures, self.pages = defaultdict(list), {}
        self.column_sources = defaultdict(list)
        self.later_witnesses = {}
        self.grids_for_page, self.panel_grids = grids_for_page, {}
        self.panel_pixels = {}
        self.source_cells = defaultdict(list)
        for cell in source_cells:
            if cell.column_ownership is not None:
                self.source_cells[cell.column_ownership.get("source_anchor_id")].append(
                    cell
                )
        for section in source_sections:
            if section.get("role") in COLUMN_SOURCE_ROLES:
                self.column_sources[section["page_no"]].append(section)
        if len(structures) > MAX_DECLARATION_STRUCTURES:
            raise ValueError("Original heading structure inventory exceeds its bound")
        identities = set()
        for structure in structures:
            sid, number = str(structure["id"]), structure["page_no"]
            if (
                type(number) is not int
                or not 1 <= number <= len(doc)
                or sid in identities
                or structure.get("source_pdf_sha256", original_sha) != original_sha
            ):
                raise ValueError("Foreign or duplicate original heading structure")
            identities.add(sid)
            self.structures[number].append(
                {
                    "structure_id": sid,
                    "bbox": [structure[k] for k in ("x0", "y0", "x1", "y1")],
                }
            )

    def _page(self, page_no):
        if page_no not in self.pages:
            page = self.doc[page_no - 1]
            self.pages[page_no] = {
                "page_no": page_no,
                "page_size": [page.rect.width, page.rect.height],
                "lines": [
                    {
                        "text": row["text"],
                        "bbox": list(row["bbox"]),
                        "source": row["source"],
                    }
                    for row in heading_line_windows(self.lines_for_page(page_no))
                ],
                "structures": self.structures[page_no],
            }
            if not _page_valid(self.pages[page_no]):
                raise ValueError("Malformed original heading page observation")
        return self.pages[page_no]

    def observe(self, heading):
        pages, later_columns, stop = [], [], None
        first_page = self.doc[heading["page_no"] - 1]
        if first_page.number not in self.panel_grids:
            if self.grids_for_page is not None:
                grids = self.grids_for_page(first_page)
            else:
                from .table_geometry import detect_ruled_table_regions

                grids = detect_ruled_table_regions(
                    first_page, dpi=240, minimum_columns=1
                )
            self.panel_grids[first_page.number] = grids
        panel = observe_panel(
            first_page,
            heading,
            self.panel_grids[first_page.number],
            pixel_cache=self.panel_pixels,
        )
        column_sources = self.column_sources[heading["page_no"]]
        columns = independent_columns(
            column_sources, self._page(heading["page_no"]), heading
        )
        for number in range(
            heading["page_no"],
            min(len(self.doc), heading["page_no"] + MAX_DECLARATION_PAGES - 1) + 1,
        ):
            page = self._page(number)
            pages.append(page)
            if number != heading["page_no"]:
                if number not in self.later_witnesses:
                    self.later_witnesses[number] = [
                        {
                            "section": section,
                            "cells": capture_column_cells(
                                self.source_cells[section["region_id"]], section
                            ),
                            "caption_frames": capture_caption_frames(
                                self.doc[number - 1],
                                column_caption_boxes(
                                    section["source"]["header_scope"], page
                                ),
                                page["page_size"],
                            ),
                        }
                        for section in self.column_sources[number]
                    ]
                witnesses = self.later_witnesses[number]
                later_columns.append({"page_no": number, "sources": witnesses})
                current_columns = later_page_columns(witnesses, page, heading)
            else:
                current_columns = columns
            boundary, _cell, _complete = declaration_window(
                page, heading, current_columns, panel
            )
            if boundary:
                stop = {"kind": boundary[1], "page_no": number, "y": boundary[0]}
            elif number == len(self.doc):
                stop = {
                    "kind": "document_end",
                    "page_no": number,
                    "y": page["page_size"][1],
                }
            if stop:
                break
        if stop is None:
            page = pages[-1]
            stop = {
                "kind": "page_limit",
                "page_no": page["page_no"],
                "y": page["page_size"][1],
            }
        scope = {
            "version": 4 if panel is not None else 3,
            "status": "observed_declaration",
            "original_pdf_sha256": self.original_sha,
            "heading_source_id": proof_id(heading),
            "document_page_count": len(self.doc),
            "pages": pages,
            "column_sources": column_sources,
            "later_columns": later_columns,
            "stop": stop,
            **({"panel": panel} if panel is not None else {}),
        }
        try:
            declaration_candidates(scope, heading)
        except SourceEvidenceLimit:
            if panel is None or panel["pixels"] is None:
                raise
            # Refuse the WHOLE panel proof, never trim pixels into acceptance or
            # retry it. The original PDF and complete page inventory survive.
            scope["panel"] = {**panel, "pixels": None, "refusal": "region_budget"}
            if panel["cell"] is not None:
                self.panel_pixels[(first_page.number, *panel["cell"])] = (
                    None,
                    "region_budget",
                )
            scope["stop"] = {
                "kind": "unproved_panel",
                "page_no": heading["page_no"],
                "y": heading["nomination"]["bbox"][3],
            }
            declaration_candidates(scope, heading)
        return scope
