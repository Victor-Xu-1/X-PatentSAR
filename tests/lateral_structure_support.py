"""Generated original parallel-column pages through the real binding facade."""

import json
import tempfile
from pathlib import Path

import fitz

from patent_sar_extractor.core.structure_binder import bind


class LateralStructureControls:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="original-lateral-sources-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_case(
        self,
        *,
        nonfinal=False,
        later_product=False,
        raster=False,
        duplicate=False,
        shared_title=False,
        left_later_centre=510,
        native_conflict=False,
        selected=False,
        selected_novel=False,
        ruled=True,
        right_title_y=45,
        mutate_document=None,
    ):
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=self.temporary.name))
        original, records = self.root / "original.pdf", []
        with fitz.open() as document:
            page = document.new_page(width=660, height=720)
            for column, left in enumerate((40, 360)):
                title = (
                    "Table 11. Compounds"
                    if column == 0
                    else (
                        "Table B8. Intermediates" if nonfinal else "Table B8. Compounds"
                    )
                )
                if shared_title:
                    title = "Table 11. Intermediates" if column == 0 else ""
                elif selected and column == 1:
                    title = "Table B8. Selected compounds"
                if title:
                    page.insert_text(
                        (left, right_title_y if column else 45), title, fontsize=9
                    )
                page.insert_text((left + 5, 80), "Compound No.", fontsize=8)
                page.insert_text((left + 110, 80), "Structure", fontsize=8)
                xs = [left, left + 80, left + 260]
                ys = (
                    [65, 100, 210, 380, 600]
                    if later_product and column == 0
                    else [65, 100, 210, 330]
                )
                if ruled:
                    self.draw_grid(page, xs, ys)
                labels = (
                    ["73", "28"]
                    if column == 0
                    else ["73" if duplicate else "901A", "I-003B"]
                )
                if selected and column == 1:
                    labels = ["73", "I-003B" if selected_novel else "28"]
                centres = [150, 265]
                if later_product and column == 0:
                    labels.append("A17")
                    centres.append(left_later_centre)
                for label, centre in zip(labels, centres, strict=True):
                    page.insert_text((left + 15, centre + 4), label, fontsize=10)
                    self.add_drawing(page, records, left, centre, f"C{column}-{label}")
            if later_product:
                page.insert_text((360, 430), "Compound B80: Preparation", fontsize=10)
                self.add_drawing(page, records, 360, 510, "LATER-B80")
            if mutate_document is not None:
                mutate_document(document, records)
            if raster:
                with fitz.open() as scanned:
                    for original_page in document:
                        target = scanned.new_page(width=660, height=720)
                        target.insert_image(
                            target.rect,
                            stream=original_page.get_pixmap(
                                matrix=fitz.Matrix(4, 4), alpha=False
                            ).tobytes("png"),
                        )
                        if native_conflict and original_page.number == 0:
                            target.insert_text(
                                (360, right_title_y),
                                "Table B8. Compounds",
                                fontsize=9,
                                render_mode=3,
                            )
                    scanned.save(original)
            else:
                document.save(original)
        with fitz.open(original) as document:
            for record in records:
                image = self.root / (record["structure_id"] + ".png")
                document[record["page_no"] - 1].get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    clip=fitz.Rect(record["bbox_pdf"]),
                    alpha=False,
                ).save(image)
                record["image_path"] = str(image)
        metadata = self.root / "structures.json"
        metadata.write_text(
            json.dumps({"patent_number": "CONTROL-LATERAL", "structures": records})
        )
        result = bind(
            str(original),
            {"structure_candidate_pages": sorted({r["page_no"] - 1 for r in records})},
            str(self.root / "bindings"),
            str(metadata),
        )
        payload = json.loads(Path(result["output_files"]["json"]).read_text())
        return result, payload

    @staticmethod
    def draw_grid(page, xs, ys):
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))

    @staticmethod
    def add_drawing(page, records, left, centre, identity):
        page.draw_polyline(
            [
                (left + 105, centre - 15),
                (left + 130, centre - 30),
                (left + 160, centre - 15),
                (left + 160, centre + 15),
                (left + 130, centre + 30),
                (left + 105, centre + 15),
                (left + 105, centre - 15),
            ],
            width=1.5,
        )
        page.draw_line((left + 160, centre - 15), (left + 205, centre - 25), width=1.5)
        records.append(
            {
                "structure_id": identity,
                "structure_index": len(records),
                "page_no": page.number + 1,
                "bbox_pdf": [left + 95, centre - 35, left + 235, centre + 35],
            }
        )
