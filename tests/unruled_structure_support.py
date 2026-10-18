"""Generated original pages exercise the actual binder, never private patents."""

import json
import tempfile
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.structure_binder import bind


class UnruledStructureControls:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="original-unruled-columns-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_binding(
        self,
        labels,
        *,
        raster=False,
        missing_graph=None,
        missing_label=None,
        reverse=False,
        title="Table 12. Compounds",
        identifier_header="Compound No.",
        structure_header="Structure",
        header_baselines=(80, 80),
        label_baseline_offset=4,
        native_overlay=None,
        mutate_page=None,
    ):
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=self.temporary.name))
        original = self.root / "original.pdf"
        structures = []
        page_height = max(720, 200 + max(0, len(labels) - 1) * 115)
        with fitz.open() as document:
            page = document.new_page(width=520, height=page_height)
            page.insert_text((40, 45), title, fontsize=10)
            page.insert_text((50, header_baselines[0]), identifier_header, fontsize=10)
            page.insert_text((240, header_baselines[1]), structure_header, fontsize=10)
            for row, label in enumerate(labels):
                centre = 150 + row * 115
                if row != missing_label:
                    page.insert_text(
                        (60, centre + label_baseline_offset), label, fontsize=10
                    )
                if row == missing_graph:
                    continue
                bounds = (215, centre - 35, 355, centre + 35)
                page.draw_polyline(
                    [
                        (230, centre - 15),
                        (255, centre - 30),
                        (285, centre - 15),
                        (285, centre + 15),
                        (255, centre + 30),
                        (230, centre + 15),
                        (230, centre - 15),
                    ],
                    width=1.5,
                )
                page.draw_line((285, centre - 15), (335, centre - 25), width=1.5)
                image = self.root / f"S{row}.png"
                page.get_pixmap(
                    matrix=fitz.Matrix(2, 2), clip=fitz.Rect(bounds), alpha=False
                ).save(image)
                structures.append(
                    {
                        "structure_id": f"S{row}",
                        "structure_index": row,
                        "page_no": 1,
                        "bbox_pdf": bounds,
                        "image_path": str(image),
                    }
                )
            if mutate_page:
                mutate_page(page, structures)
            for structure in structures:
                image = self.root / (structure["structure_id"] + ".png")
                document[structure["page_no"] - 1].get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    clip=fitz.Rect(structure["bbox_pdf"]),
                    alpha=False,
                ).save(image)
                structure["image_path"] = str(image)
            if raster:
                with fitz.open() as scanned:
                    for source in document:
                        pixels = source.get_pixmap(
                            matrix=fitz.Matrix(4, 4), alpha=False
                        )
                        target = scanned.new_page(
                            width=source.rect.width, height=source.rect.height
                        )
                        target.insert_image(target.rect, stream=pixels.tobytes("png"))
                        if native_overlay:
                            native_overlay(target)
                    scanned.save(original)
            else:
                document.save(original)
        if reverse:
            structures.reverse()
        metadata = self.root / "structures.json"
        metadata.write_text(
            json.dumps(
                {"patent_number": "CONTROLLED-COLUMNS", "structures": structures}
            )
        )
        result = bind(
            str(original),
            {"structure_candidate_pages": [0]},
            str(self.root / "bindings"),
            str(metadata),
        )
        payload = load_json(Path(result["output_files"]["json"]), None)
        return result, payload
