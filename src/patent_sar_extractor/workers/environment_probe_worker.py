"""Offline real-version/module/model probe in the selected external interpreter."""

from __future__ import annotations

import importlib.metadata
import pickle
import subprocess
import sys
from pathlib import Path

# Prefer this operation's first-party probe helpers, not an older installed
# X-PatentSAR. Third-party packages remain exclusively in the child interpreter.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patent_sar_extractor.workers.analysis_protocol import (
    emit,
    prepare,
    read_request,
)
from patent_sar_extractor.workers.environment_files import (
    load_json,
    read_regular,
    verify_decimer_models,
)


def versions(names: list[str]) -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in names}


def probe(request: dict[str, object]) -> dict[str, object]:
    role = request.get("role")
    result: dict[str, object] = {"python": sys.version.split()[0], "checks": []}
    checks = result["checks"]
    assert isinstance(checks, list)

    def check(name: str, ok: bool, message: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "message": message})

    if role == "installer":
        completed = subprocess.run(
            [str(request["uv_path"]), "--version"],
            capture_output=True,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            check=False,
        )
        text = completed.stdout[:4096].decode("utf-8")
        check(
            "version",
            completed.returncode == 0 and text.startswith("uv 0.11.31 "),
            "Actual owned uv --version",
        )
    elif role == "base":
        found = versions(["PyMuPDF", "rapidocr-onnxruntime", "rdkit"])
        expected = {
            "PyMuPDF": "1.27.2.3",
            "rapidocr-onnxruntime": "1.4.4",
            "rdkit": "2026.3.1",
        }
        check("python", sys.version_info[:2] == (3, 12), "Requires native Python 3.12")
        check(
            "versions", found == expected, "Pinned PDF/RapidOCR/RDKit versions checked"
        )
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        from rapidocr_onnxruntime import RapidOCR
        from rdkit import Chem, rdBase

        with fitz.open() as pdf:
            pdf.new_page().insert_text((30, 30), "PatentSAR parser check")
            content = pdf.tobytes()
        with fitz.open(stream=content, filetype="pdf") as parsed:
            check(
                "pdf_parser",
                parsed.page_count == 1 and "parser check" in parsed[0].get_text(),
                "Actual PyMuPDF round-trip",
            )
        with rdBase.BlockLogs():
            check(
                "rdkit",
                Chem.MolFromSmiles("CCO") is not None
                and Chem.MolFromSmiles("invalid-SMILES") is None,
                "Actual RDKit sanitize success/failure",
            )
        image = Image.new("RGB", (900, 180), "white")
        ImageDraw.Draw(image).text(
            (30, 45),
            "PATENTSAR 123",
            font=ImageFont.load_default(size=60),
            fill="black",
        )
        output, _ = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)(image)
        text = " ".join(str(row[1]) for row in output or [])
        check("rapidocr", "123" in text, "Actual bundled ONNX OCR inference")
        result["versions"] = found
    elif role in {"admet", "admet-models"}:
        import torch
        from admet_ai import ADMETModel

        found = versions(
            ["admet-ai", "chemprop", "torch", "rdkit", "numpy", "lightning"]
        )
        check("python", sys.version_info[:2] == (3, 12), "Requires Python 3.12")
        check(
            "versions",
            found["admet-ai"] == "2.0.1"
            and found["chemprop"] == "2.2.2"
            and found["torch"] == "2.8.0+cpu",
            "Pinned ADMET/Chemprop/CPU Torch versions",
        )
        check(
            "cpu_only",
            torch.version.cuda is None and not torch.cuda.is_available(),
            "Actual CPU-only Torch build",
        )
        result["versions"] = found
        if role == "admet-models":
            from patent_sar_extractor.workers.admet_models import existing_bundle

            root = Path(str(request["model_root"]))
            existing_bundle(root)
            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)
            model = ADMETModel(
                models_dir=root / "models", drugbank_path=None, num_workers=0
            )
            check(
                "models_loaded",
                sum(len(group) for group in model.model_lists) == 10
                and model.num_ensembles == 2,
                "Actual 10-model load; no predictive-accuracy acceptance",
            )
            check(
                "reference_disabled", model.drugbank is None, "DrugBank is not loaded"
            )
    elif role in {"decimer", "decimer-ocsrc", "decimer-segmentation"}:
        found = versions(["DECIMER", "DECIMER-Segmentation", "tensorflow", "numpy"])
        check("python", result["python"] == "3.10.20", "Requires Python 3.10.20")
        check(
            "versions",
            found
            == {
                "DECIMER": "2.8.0",
                "DECIMER-Segmentation": "1.5.0",
                "tensorflow": "2.15.1",
                "numpy": "1.26.4",
            },
            "Pinned DECIMER/Segmentation/TF/NumPy versions",
        )
        import decimer_segmentation
        import tensorflow as tf

        tf.config.set_visible_devices([], "GPU")
        check(
            "modules",
            hasattr(decimer_segmentation, "get_model"),
            "Actual TensorFlow and segmentation imports",
        )
        result["versions"] = found
        distribution = importlib.metadata.distribution("DECIMER-Segmentation")
        result["segmentation_path"] = str(
            distribution.locate_file("decimer_segmentation/mask_rcnn_molecule.h5")
        )
        if role != "decimer":
            root = Path(str(request["model_root"]))
            recipe = load_json(Path(str(request["recipe"])))
            verify_decimer_models(root, recipe)
            check(
                "ocsrc_fingerprint",
                True,
                "Two SavedModel/tokenizer contents verified before deserialization",
            )
            if role == "decimer-ocsrc":
                name = str(request.get("model_name"))
                if name not in {"DECIMER_model", "DECIMER_HandDrawn_model"}:
                    raise ValueError("Unknown fixed OCSR model")
                # DECIMER imports both SavedModels eagerly. Load each identical
                # verified artifact in its own process to keep the RSS bound.
                model = tf.saved_model.load(str(root / "DECIMER-V2" / name))
                check(
                    "ocsrc_loaded",
                    callable(model),
                    f"Actual {name} TensorFlow load; not accuracy acceptance",
                )
                tokenizer_name = (
                    "tokenizer_SMILES.pkl"
                    if name == "DECIMER_model"
                    else "tokenizer_pubchem.pkl"
                )
                tokenizer = pickle.loads(
                    read_regular(
                        root / "DECIMER-V2" / name / "assets" / tokenizer_name,
                        16 * 1024,
                    )
                )
                check(
                    "tokenizer_loaded",
                    bool(getattr(tokenizer, "word_index", None)),
                    "Official hash-verified tokenizer loaded",
                )
            else:
                from patent_sar_extractor.workers.environment_segmentation import (
                    configure_segmentation_model,
                )

                external = root / "segmentation/mask_rcnn_molecule.h5"
                chosen = (
                    external
                    if external.is_file()
                    else Path(str(result["segmentation_path"]))
                )
                model = configure_segmentation_model(chosen)
                check(
                    "segmentation_loaded",
                    len(model.keras_model.weights) > 0,
                    "Actual official MaskRCNN weights load via explicit adapter",
                )
        check(
            "cpu_only",
            not tf.config.get_visible_devices("GPU"),
            "TensorFlow visible GPU devices disabled",
        )
    else:
        raise ValueError("Probe role is outside the fixed allowlist")
    return result


def main() -> None:
    output = prepare()
    try:
        emit(output, {"ok": True, "result": probe(read_request())})
    except Exception as exc:  # noqa: BLE001 - SDK exceptions are sanitized at the child boundary
        print(f"Environment probe failed type={type(exc).__name__}", file=sys.stderr)
        emit(output, {"ok": False, "code": "runtime_unavailable"})
    finally:
        output.close()


if __name__ == "__main__":
    main()
