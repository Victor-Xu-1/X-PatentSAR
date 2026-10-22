"""Normal binder -> plan -> worker/Web must retain non-molecular figure owners."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from catalog_source_support import original_catalogue
from recognition_source_support import complete_observation_artifact

from patent_sar_extractor import contracts
from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.core.binding_source_references import reference_scope
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.ocsr.candidate_coverage import candidate_coverage_errors
from patent_sar_extractor.core.ocsr.candidate_inputs import load_source_observation_plan
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.web.candidate_observations import read_source_observations
from patent_sar_extractor.web.files import SafeFiles
from tests.test_plot_legend_rows import two_row_plot


class PlotSourceConsumerTests(unittest.TestCase):
    def test_real_binder_plan_and_web_reopen_every_original_figure_source(self):
        for raster in (False, True):
            with (
                self.subTest(raster=raster),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                metadata_path = root / "structures/metadata.json"
                write_json_atomic(
                    metadata_path,
                    contracts.artifact_identity(
                        contracts.STRUCTURES_SCHEMA,
                        contracts.STRUCTURES_SCHEMA_VERSION,
                    ),
                )

                def extra_pages(document, *, raster=raster):
                    with two_row_plot(
                        y_values=("150", "100", "25"), middle_tick="10"
                    ) as drawing:
                        if raster:
                            page = document.new_page(width=540, height=480)
                            page.insert_image(
                                page.rect,
                                stream=drawing[0].get_pixmap(dpi=240).tobytes("png"),
                            )
                        else:
                            document.insert_pdf(drawing)

                pdf, _, bindings = original_catalogue(
                    root,
                    root,
                    labels=("001B", "002B"),
                    identities=("controlled-a", "controlled-b"),
                    selected=False,
                    extra_pages=extra_pages,
                )
                sources = recognition_inputs(bindings)
                self.assertEqual(len(sources.plot_references), 1)
                sha = bindings["source_reference_scope"]["original_pdf_sha256"]
                plan = load_source_observation_plan(
                    sources,
                    structures_json=metadata_path,
                    pdf_path=pdf,
                    binding_dir=root / "structure_bindings",
                    binding_pdf_sha256=sha,
                )
                self.assertTrue(
                    plan.proven.plot_references == sources.plot_references,
                    "Path resolution dropped the original figure source",
                )
                self.assertEqual(len(plan.proven.work_items), 2)
                observed = complete_observation_artifact(
                    bindings,
                    pdf=pdf,
                    structures=metadata_path,
                    binding_dir=root / "structure_bindings",
                )
                payloads = {
                    "structures": load_json(metadata_path, {}),
                    "bindings": bindings,
                    "smiles": observed,
                }
                changed = copy.deepcopy(bindings)
                changed_proof = next(
                    section["heading_observation"]
                    for section in changed["source_sections"]
                    if section["role"] == "figure_label_reference"
                )
                pixels = changed_proof["figure_source"]["marker"]["readings"][0]
                pixels["pixel_sha256"] = "0" * 64
                pixels["source_window"]["source_pixel_sha256"] = "0" * 64
                changed["source_reference_scope"] = reference_scope(
                    changed["source_sections"], sha
                )
                self.assertIsNotNone(proved_heading_declaration(changed_proof))

                def changed_original(path=pdf):
                    document = fitz.open(path)
                    # The normal binder has a precise one-row owner. Change
                    # its retained graphic key; coarse non-target-row replay
                    # is independently exercised in test_plot_original_replay.
                    document[1].draw_line((325, 110), (341, 110), width=1)
                    return document

                with patch(
                    "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
                    side_effect=AssertionError("Worker/Web readback cannot repeat OCR"),
                ):
                    files = SafeFiles(root)
                    self.assertEqual(
                        candidate_coverage_errors(
                            root,
                            {"input_pdf": str(pdf)},
                            payloads["structures"],
                            bindings,
                            observed,
                        ),
                        [],
                    )
                    self.assertTrue(
                        candidate_coverage_errors(
                            root,
                            {"input_pdf": str(pdf)},
                            payloads["structures"],
                            changed,
                            observed,
                        )
                    )
                    self.assertEqual(
                        read_source_observations(
                            files,
                            payloads,
                            sha,
                            open_original=lambda path=pdf: fitz.open(path),
                        ).errors,
                        [],
                    )
                    self.assertTrue(
                        read_source_observations(
                            files,
                            payloads,
                            sha,
                            open_original=changed_original,
                        ).errors
                    )


if __name__ == "__main__":
    unittest.main()
