"""Generated raster originals sharing the normal source/worker test fixture."""

import fitz
from native_reaction_support import NativeReactionFixture


class RasterReactionFixture(NativeReactionFixture):
    def saved_source(self, *, filled=False, source_setup=None, terminal="S2"):
        return super().saved_source(
            filled=filled,
            source_transform=self.rasterize_route,
            source_setup=source_setup,
            terminal=terminal,
        )

    def rasterize_route(self, *, pixels_per_point=3):
        bounds = fitz.Rect(10, 60, 650, 590)
        pixels = self.page.get_pixmap(
            matrix=fitz.Matrix(pixels_per_point, pixels_per_point), clip=bounds
        )
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=660, height=660)
        page.insert_text((35, 40), "Preparation of Compound 037B", fontsize=12)
        page.insert_text((35, 610), "Step 1: Preparation", fontsize=11)
        page.insert_image(bounds, stream=pixels.tobytes("png"))
        self.document, self.page = document, page
        for structure in self.structures:
            box = fitz.Rect(*(structure[k] for k in ("x0", "y0", "x1", "y1")))
            page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=box).save(
                structure["image_path"]
            )
