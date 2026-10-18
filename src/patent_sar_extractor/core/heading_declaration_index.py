"""Call-local original page inventory for the single heading scope/replay policy."""

from collections import defaultdict

from .heading_declaration_scope import (
    MAX_DECLARATION_PAGES,
    MAX_DECLARATION_STRUCTURES,
    _page_valid,
    _stop,
    declaration_candidates,
)
from .heading_line_windows import heading_line_windows
from .source_evidence_identity import proof_id


class HeadingDeclarationIndex:
    """Shared original pages; no new store, OCR, queue or identifier guess."""

    def __init__(self, doc, structures, lines_for_page, original_sha):
        self.doc, self.lines_for_page, self.original_sha = (
            doc,
            lines_for_page,
            original_sha,
        )
        self.structures, self.pages = defaultdict(list), {}
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
        pages, stop = [], None
        for number in range(
            heading["page_no"],
            min(len(self.doc), heading["page_no"] + MAX_DECLARATION_PAGES - 1) + 1,
        ):
            page = self._page(number)
            pages.append(page)
            boundary = _stop(page, heading)
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
            "version": 1,
            "status": "observed_declaration",
            "original_pdf_sha256": self.original_sha,
            "heading_source_id": proof_id(heading),
            "document_page_count": len(self.doc),
            "pages": pages,
            "stop": stop,
        }
        declaration_candidates(scope, heading)
        return scope
