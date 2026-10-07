"""E-drive fixture builders; synthetic artifacts test adapters, not extraction."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from patent_sar_extractor import contracts
from patent_sar_extractor.web.acceptance import ARTIFACTS
from patent_sar_extractor.web.app import create_app
from patent_sar_extractor.web.processes import RunSpec, SubprocessRunner

TEST_ROOT = Path(
    os.environ.get(
        "PATENTSAR_WEB_TEST_ROOT", str(Path(tempfile.gettempdir()) / "x-patentsar-api")
    )
)
BASE_URL = "http://127.0.0.1:18765"


class WebFixture:
    def setUp(self):
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="web-", dir=TEST_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.pdf = make_pdf(self.root / "input.pdf")

    def app(self, **kwargs):
        return create_app(
            self.state,
            host=kwargs.pop("host", "127.0.0.1"),
            port=kwargs.pop("port", 18765),
            **kwargs,
        )

    @contextmanager
    def client(self, **kwargs):
        with TestClient(self.app(**kwargs), base_url=BASE_URL) as client:
            csrf = client.get("/api/v1/session").json()["csrf_token"]
            client.headers.update({"Origin": BASE_URL, "X-CSRF-Token": csrf})
            yield client

    def upload(self, client, data=None):
        response = client.post(
            "/api/v1/projects?filename=WO1234567.pdf",
            content=data or self.pdf.read_bytes(),
            headers={"Content-Type": "application/pdf"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()


def make_pdf(
    path: Path,
    *,
    rotation=0,
    encrypted=False,
    text="Controlled local PDF evidence for the authenticated Web API integration",
) -> Path:
    with fitz.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_text((20, 25), text, fontsize=9)
        page.draw_rect(fitz.Rect(20, 40, 120, 140), color=(1, 0, 0), fill=(1, 0, 0))
        page.set_rotation(rotation)
        options = (
            {
                "encryption": fitz.PDF_ENCRYPT_AES_256,
                "owner_pw": "owner",
                "user_pw": "user",
            }
            if encrypted
            else {}
        )
        document.save(path, **options)
    return path


def artifact_run(
    root: Path, pdf: Path, *, current=True, accepted=True, rows=2, rendered=True
) -> Path:
    """Small contract fixtures. These are NOT evidence of a successful core run."""
    root.mkdir()
    ids = [f"Compound {number}" for number in range(rows, 0, -1)]
    bounds = [20, 40, 120, 140]
    with fitz.open(pdf) as document:
        displayed_bounds = fitz.Rect(bounds) * document[0].rotation_matrix
        if rendered:
            bounds = list(displayed_bounds)
        # Rendering is always in display space; only recorded geometry changes.
        image = document[0].get_pixmap(clip=displayed_bounds)
    crop = root / "crop.png"
    image.save(crop)
    payloads = {
        name: contracts.artifact_identity(schema, version)
        for name, (_, schema, version) in ARTIFACTS.items()
    }
    if not current:
        for payload in payloads.values():
            payload["ruleset"]["version"] = "2.0.0"
    payloads["summary"].update(
        {
            "patent_id": "WO1234567",
            "status": "complete",
            "steps": {"activity": {"status": "ok", "rows": rows, "elapsed_s": 1.25}},
        }
    )
    payloads["classification"]["page_count"] = 1
    payloads["classification"]["activity_pages"] = [0]
    payloads["activity"].update(
        {
            "active_cpds": ids,
            "rows": [
                {
                    "cpd": cpd,
                    "activity_values": {"IC50(nM)": str(i + 1)},
                    "page_no": 1,
                    "target": "Measured target",
                    "assay": "Measured assay",
                }
                for i, cpd in enumerate(ids)
            ],
        }
    )
    bindings = [
        {
            "cpd": cpd,
            "compound_id": cpd,
            "structure_id": f"S{i}",
            "page_no": 1,
            "image_path": str(crop),
            "struct_x0": bounds[0],
            "struct_y0": bounds[1],
            "struct_x1": bounds[2],
            "struct_y1": bounds[3],
            "struct_area": 10000,
            "struct_width": 100,
            "struct_height": 100,
            "binding_rule": "structure_table_row_order",
            "authoritative_table_source_label": cpd,
            "authoritative_table_correction_reason": "Original observed label",
        }
        for i, cpd in enumerate(ids)
    ]
    payloads["bindings"].update(
        {"execution_mode": "production_structure_led", "final_bindings": bindings}
    )
    from patent_sar_extractor.core.binding_catalog import compound_catalog

    payloads["bindings"]["compound_catalog"] = compound_catalog(bindings, [])
    # Formal source order uses the same catalog; these fixtures do not certify
    # the depicted red-square crop as an actual scientific molecular graph.
    payloads["bindings"]["final_bindings"] = payloads["bindings"]["compound_catalog"][
        "entries"
    ]
    payloads["structures"]["structures"] = [
        {
            "structure_id": f"S{i}",
            "page_no": 1,
            "image_path": str(crop),
            **({"bbox_pdf": bounds} if rendered else {}),
        }
        for i in range(rows)
    ]
    payloads["smiles"].update(
        {
            "execution_mode": "production_decimer",
            "records": [
                {
                    "cpd_id": b["cpd"],
                    "structure_id": b["structure_id"],
                    "smiles": "CCO",
                    "rdkit_valid": True,
                }
                for b in payloads["bindings"]["final_bindings"]
            ],
        }
    )
    from patent_sar_extractor.core.ocsr.smiles_qc import qc_smiles
    from patent_sar_extractor.core.ocsr.stereo_evidence import (
        observe_stereo_symbols,
        source_checked_qc,
    )

    screened = source_checked_qc(
        qc_smiles("CCO"), observe_stereo_symbols(crop.read_bytes())
    )
    for record in payloads["smiles"]["records"]:
        record.update(
            screened,
            OCSR_quality_flag=screened["quality_flag"],
            OCSR_status="success",
            raw_smiles="CCO",
            image_hash=screened["stereochemistry"]["image_sha256"],
        )
    # This is genuine syntax/risk-screen contract data for an explicit controlled
    # graph, NOT a claim that the fixture's red crop was recognized as ethanol.
    payloads["qa"].update(
        {
            "ok": accepted,
            "acceptance": {
                "ok": accepted,
                "hard_errors": []
                if accepted
                else ["Controlled deterministic rejection"],
            },
        }
    )
    for name, payload in payloads.items():
        destination = root / ARTIFACTS[name][0]
        destination.parent.mkdir(exist_ok=True, parents=True)
        destination.write_text(json.dumps(payload))
    ocr = {
        "metadata": {
            **contracts.artifact_identity(
                contracts.PAGE_OCR_CACHE_SCHEMA, contracts.PAGE_OCR_CACHE_SCHEMA_VERSION
            ),
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "page_count": 1,
        },
        "page_texts": {"0": "Historical observed OCR text"},
    }
    (root / "page_classification/page_ocr_cache.json").write_text(json.dumps(ocr))
    return root


class SleepRunner(SubprocessRunner):
    def command(self, spec: RunSpec) -> list[str]:
        return [
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            spec.job_id,
            spec.output_dir,
        ]


class ExitRunner(SubprocessRunner):
    def command(self, spec: RunSpec) -> list[str]:
        return [
            sys.executable,
            "-c",
            "import time; time.sleep(.15); raise SystemExit(7)",
            spec.job_id,
            spec.output_dir,
        ]


class DetachedRunner(SubprocessRunner):
    def command(self, spec: RunSpec) -> list[str]:
        code = "import subprocess,sys,pathlib,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True); pathlib.Path('child.pid').write_text(str(p.pid)); time.sleep(30)"
        return [sys.executable, "-c", code, spec.job_id, spec.output_dir]


def wait_job(client, job_id, status, *, timeout=8):
    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        if response.status_code != 200:
            raise AssertionError(response.text)
        result = response.json()
        if result["status"] == status:
            return result
        time.sleep(0.03)
    raise AssertionError(f"Job did not reach {status}: {result}")
