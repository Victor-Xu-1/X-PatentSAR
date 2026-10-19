"""Normal binder artifacts and safe Web source reads share original role replay."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from catalog_source_support import original_catalogue
from recognition_source_support import complete_observation_artifact

from patent_sar_extractor import contracts
from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.web.candidate_observations import read_source_observations
from patent_sar_extractor.web.files import SafeFiles
from tests import test_role_grid_coverage as role_controls


class OriginalRoleWebTests(unittest.TestCase):
    def _assert_sources(self, *, raster_roles):
        with tempfile.TemporaryDirectory(prefix="ordinary-role-web-") as temporary:
            root = Path(temporary)
            metadata_path = root / "structures/metadata.json"
            write_json_atomic(
                metadata_path,
                contracts.artifact_identity(
                    contracts.STRUCTURES_SCHEMA, contracts.STRUCTURES_SCHEMA_VERSION
                ),
            )

            def extra_pages(document):
                fixture = role_controls.RoleGridCoverageTests()
                try:
                    page, _grid, _tokens, _identifiers = fixture.original(2)
                    if raster_roles:
                        with fitz.open() as flattened:
                            raster = flattened.new_page(
                                width=page.rect.width, height=page.rect.height
                            )
                            raster.insert_image(
                                raster.rect,
                                stream=page.get_pixmap(
                                    matrix=fitz.Matrix(3, 3), alpha=False
                                ).tobytes("png"),
                            )
                            document.insert_pdf(flattened)
                    else:
                        document.insert_pdf(
                            page.parent, from_page=page.number, to_page=page.number
                        )
                finally:
                    fixture.doCleanups()

            pdf, _records, bindings = original_catalogue(
                root,
                root,
                labels=("001B", "002B"),
                identities=("controlled-a", "controlled-b"),
                selected=False,
                extra_pages=extra_pages,
            )
            regions = [
                section["source_region"]
                for section in bindings["source_sections"]
                if section["role"] == "characterization_region"
            ]
            self.assertEqual(len(regions), 1)
            self.assertEqual(regions[0]["page_no"], 2)
            self.assertEqual(
                [view["method"] for view in regions[0]["role_scope"]["observations"]],
                ["cell_ocr_400dpi", "cell_ocr_600dpi"]
                if raster_roles
                else ["native_cells"],
            )
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
            sha = bindings["source_reference_scope"]["original_pdf_sha256"]
            files = SafeFiles(root)
            with patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                side_effect=AssertionError("Safe source reads cannot load a model"),
            ):
                self.assertTrue(read_source_observations(files, payloads, sha).errors)
                self.assertEqual(
                    read_source_observations(
                        files, payloads, sha, open_original=lambda: fitz.open(pdf)
                    ).errors,
                    [],
                )

                def changed_original():
                    document = fitz.open(pdf)
                    region = regions[0]
                    scope = region["role_scope"]
                    document[region["page_no"] - 1].insert_text(
                        (scope["xs"][-2] + 5, scope["ys"][-2] + 15),
                        "IC50 = 3 nM",
                        fontsize=6,
                    )
                    return document

                self.assertTrue(
                    read_source_observations(
                        files, payloads, sha, open_original=changed_original
                    ).errors
                )

    def test_native_binder_worker_and_web_conserve_non_molecular_role_sources(self):
        self._assert_sources(raster_roles=False)

    def test_raster_binder_worker_and_web_conserve_non_molecular_role_sources(self):
        self._assert_sources(raster_roles=True)
