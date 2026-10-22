"""Read-only original replay of later-page exclusion witnesses; no text model."""

from .activity_context_geometry import grid_axes
from .cell_frame_proof import original_cell_frame_matches
from .heading_column_captions import caption_frame_at
from .heading_column_replay import column_header_sources
from .heading_evidence import original_heading_lines
from .heading_line_windows import heading_line_windows
from .heading_page_columns import later_page_columns
from .native_cell_replay import original_native_cell_matches
from .source_evidence_identity import proof_id
from .source_geometry import SourceTokens, source_layout
from .source_observations import source_cell_observation
from .structure_table_headers import aligned_column_edges
from .table_geometry import detect_ruled_table_regions
from .text_ocr.cell_proof import has_auxiliary_text, replay_auxiliary_cell
from .unruled_scope import scope_roles


def _axis_slice(expected, actual):
    return any(
        aligned_column_edges(expected, actual[start : start + len(expected)])
        for start in range(len(actual) - len(expected) + 1)
    )


class HeadingPageReplay:
    """Call-local source/layout memoization belongs to the caller's open PDF."""

    def __init__(self, document):
        self.document = document
        self.layouts, self.grids = {}, {}
        self.line_inventories, self.checked_sources = {}, set()

    def _layout(self, number):
        if number not in self.layouts:
            self.layouts[number] = source_layout(self.document[number - 1])
        return self.layouts[number]

    def _native_packet(self, number, packet):
        if packet.get("origin") != "native":
            return
        layout = self._layout(number)
        actual = source_cell_observation(
            SourceTokens(layout.native, layout), tuple(packet["bbox"]), native=True
        )
        if actual != packet:
            raise ValueError("Later-column native source differs from the original")

    def _reading(self, number, bounds, reading):
        page, method = self.document[number - 1], reading.get("method")
        if reading.get("bbox", bounds) != bounds:
            raise ValueError("Later-column reading leaves its original cell")
        if method == "native_cell":
            layout = self._layout(number)
            if not original_native_cell_matches(
                page, {**reading, "bbox": bounds}, layout=layout
            ):
                raise ValueError("Later-column native cell is changed or invisible")
        elif method in {"cell_ocr_400dpi", "cell_ocr_600dpi"}:
            dpi = 400 if method == "cell_ocr_400dpi" else 600
            if not original_cell_frame_matches(
                {**reading, "bbox": bounds, "render_dpi": dpi}, page
            ):
                raise ValueError("Later-column cell differs from original pixels")
        elif method != "page_ocr_cell":
            raise ValueError("Unsupported original later-column reading method")
        if has_auxiliary_text(reading) and not replay_auxiliary_cell(reading, page):
            raise ValueError("Later-column auxiliary cell differs from original pixels")

    def _source(self, number, witness):
        source = witness["section"]["source"]
        header = source["header_scope"]
        page = self.document[number - 1]
        saved_frames = witness["caption_frames"]
        # The pure policy already checked title nomination and padded geometry.
        # Replay those exact frames here without repeating text recognition.
        if [
            caption_frame_at(page, saved["bbox"]) for saved in saved_frames
        ] != saved_frames:
            raise ValueError("Later-column title differs from original pixels")
        if witness["section"]["role"] == "structure_column_anchor":
            self._grid(number, source["grid_axes"])
        for owner, kind, observed in column_header_sources(header):
            if kind == "page":
                original = self.document[owner - 1]
                if observed != [original.rect.width, original.rect.height]:
                    raise ValueError("Later-column header page geometry differs")
            elif kind == "grid":
                self._grid(owner, observed)
            elif kind == "packet":
                self._native_packet(owner, observed)
            else:
                self._reading(owner, observed["bbox"], observed)
        for chunk in source["body_context"]:
            for packet in chunk["sources"]:
                self._native_packet(number, packet)
        if witness["section"]["role"] == "structure_column_anchor":
            roles = scope_roles(header)
            xs, ys = source["grid_axes"]["xs"], source["grid_axes"]["ys"]
            for cell in witness["cells"]:
                column = roles["pairs"][cell["pair"]][0]
                row = cell["row"]
                bounds = [xs[column], ys[row], xs[column + 1], ys[row + 1]]
                for reading in cell["observations"]:
                    self._reading(number, bounds, reading)
        else:
            for cell in source["labels"]:
                for reading in cell["observations"]:
                    self._reading(number, cell["nomination"]["window"], reading)

    def _grid(self, number, expected):
        if number not in self.grids:
            self.grids[number] = [
                grid_axes(g)
                for g in detect_ruled_table_regions(self.document[number - 1])
            ]
        if not any(
            _axis_slice(expected["xs"], actual["xs"])
            and _axis_slice(expected["ys"], actual["ys"])
            for actual in self.grids[number]
        ):
            raise ValueError("Later-column printed grid differs from the original")

    def check(self, scope, heading):
        for saved in scope["pages"]:
            number = saved["page_no"]
            page = self.document[number - 1]
            if saved["page_size"] != [page.rect.width, page.rect.height]:
                raise ValueError("Original declaration page geometry differs")
            raster = [
                {
                    **line,
                    "y0": line["bbox"][1],
                    "y1": line["bbox"][3],
                    "geometry_space": "rendered",
                }
                for line in saved["lines"]
                if line["source"] == "page_ocr"
            ]
            key = (
                number,
                proof_id({"status": "original_page_lines", "raster_lines": raster}),
            )
            if key not in self.line_inventories:
                self.line_inventories[key] = [
                    {key: line[key] for key in ("text", "bbox", "source")}
                    for line in heading_line_windows(
                        original_heading_lines(page, source_lines=raster)
                    )
                ]
            observed = self.line_inventories[key]
            if observed != saved["lines"]:
                raise ValueError("Original declaration text inventory was changed")
        for witnesses, page in zip(
            scope["later_columns"], scope["pages"][1:], strict=True
        ):
            eligible = {
                col["source_id"]
                for col in later_page_columns(witnesses["sources"], page, heading)
            }
            for witness in witnesses["sources"]:
                if witness["section"]["region_id"] in eligible:
                    key = (
                        page["page_no"],
                        proof_id({"status": "original_later_column", **witness}),
                    )
                    if key not in self.checked_sources:
                        self._source(page["page_no"], witness)
                        self.checked_sources.add(key)
