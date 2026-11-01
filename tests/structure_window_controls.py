"""Generated blank-page checkpoint controls; never original chemistry acceptance."""

from pathlib import Path

import fitz

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.stage_cache import _write_step_manifest
from patent_sar_extractor.application.structure_cache import (
    _structure_chunk_fingerprint,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.structure_inventory import inventory_packet
from patent_sar_extractor.paths import PACKAGE_IMPORT_ROOT


def make_window(root, count=3):
    pdf = root / "generated.pdf"
    with fitz.open() as document:
        for _ in range(count):
            document.new_page()
        document.save(pdf)
    locator = root / "structure_pages/locator.json"
    regions = root / "structure_pages/crop_regions.json"
    write_json_atomic(
        locator,
        {
            **core.artifact_identity(
                core.STRUCTURE_LOCATION_SCHEMA, core.STRUCTURE_LOCATION_SCHEMA_VERSION
            ),
            "selected_pages": list(range(count)),
            "crop_regions": {},
        },
    )
    write_json_atomic(regions, {})
    output = root / "structures"
    jobs = []
    for index in range(count):
        folder = output / ".chunks" / f"chunk_{index:03d}"
        folder.mkdir(parents=True)
        fingerprint = _structure_chunk_fingerprint(
            pdf_path=str(pdf),
            dependencies=[str(locator), str(regions)],
            chunk_index=index,
            chunk_pages=[index],
            chunk_size=1,
            crop_regions={},
            gpu_mode="off",
        )
        jobs.append(
            {"pages": [index], "output": str(folder), "fingerprint": fingerprint}
        )
    return pdf, output, jobs


def save_chunk(job, *, count=3, seal=True, changes=None):
    path = Path(job["output"]) / "metadata.json"
    write_json_atomic(
        path,
        {
            **core.artifact_identity(
                core.STRUCTURES_SCHEMA, core.STRUCTURES_SCHEMA_VERSION
            ),
            "structures": [],
            "total_structures": 0,
            "failed_pages": [],
            "source_inventory": inventory_packet(
                count,
                [
                    {
                        "page_no": page + 1,
                        "status": "detected",
                        "scope": "full_page",
                        "candidates": 0,
                    }
                    for page in job["pages"]
                ],
            ),
            **(changes or {}),
        },
    )
    if seal:
        _write_step_manifest(str(path), job["fingerprint"])
    return path


def native_worker(root):
    """Use the actual window/sealer in a native child, without an SDK/model."""
    path = root / "generated_window.py"
    path.write_text(
        "import runpy\n"
        f"runpy.run_path({str(PACKAGE_IMPORT_ROOT / 'patent_sar_extractor/worker_bootstrap.py')!r}, run_name='__main__')\n"
        + """
import argparse, os, time
from pathlib import Path
from patent_sar_extractor import contracts as core
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.structure_inventory import inventory_packet
from patent_sar_extractor.workers.segmentation_window import execute_window
parser = argparse.ArgumentParser()
for field in ('pdf', 'output', 'patent-id', 'batch-plan'):
    parser.add_argument('--' + field, required=True)
parser.add_argument('--crop-regions', default='')
args = parser.parse_args()
write_json_atomic(Path(args.output) / 'owned-pid.json', {'pid': os.getpid()})
def extract(pdf, pages, output, regions, **kwargs):
    if pages[0] == 0:
        # A vendor can leave a filtered warning without a terminating newline.
        print('Unable to register cuDNN factory', end='', flush=True)
    if pages[0] > 0:
        deadline = time.monotonic() + 3
        while not (Path(args.output) / 'observed.ack').exists():
            if time.monotonic() >= deadline:
                raise RuntimeError('Parent did not observe saved work before child continuation')
            time.sleep(0.01)
    write_json_atomic(Path(output) / 'metadata.json', {
        **core.artifact_identity(core.STRUCTURES_SCHEMA, core.STRUCTURES_SCHEMA_VERSION),
        'structures': [], 'total_structures': 0, 'failed_pages': [],
        'source_inventory': inventory_packet(3, [
            {'page_no': page + 1, 'status': 'detected', 'scope': 'full_page', 'candidates': 0}
            for page in pages
        ]),
    })
execute_window(extract, args.batch_plan, args.pdf, args.output, args.crop_regions, args.patent_id)
""",
        encoding="utf-8",
    )
    return path
