"""Research-only consumer of the same verified printed DECIMER adapter."""

from __future__ import annotations

import importlib.metadata
import runpy
import sys
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "worker_bootstrap.py"),
    run_name="__main__",
)
from patent_sar_extractor.core.ocsr.model_identity import (
    printed_model_identity,  # noqa: E402
)
from patent_sar_extractor.core.ocsr.printed_model import (
    PrintedDecimerModel,  # noqa: E402
)
from patent_sar_extractor.workers.analysis_protocol import (  # noqa: E402
    emit,
    prepare,
    read_request,
)


def recognize(request: dict[str, object]) -> dict[str, object]:
    if set(request) != {"image_path"} or not isinstance(request["image_path"], str):
        raise ValueError("Invalid recognition request")
    image = Path(request["image_path"])
    if (
        image.is_symlink()
        or not image.is_file()
        or image.stat().st_size > 16 * 1024 * 1024
    ):
        raise ValueError("Invalid bounded crop")
    identity = printed_model_identity()
    prediction = PrintedDecimerModel(identity).predict(str(image))
    smiles = prediction["smiles"]
    if len(smiles) > 2048:
        raise ValueError("Research SMILES exceeds its size limit")
    return {
        "raw_smiles": smiles,
        "engine": {"name": "DECIMER", "version": identity["versions"]["DECIMER"]},
    }


def main() -> None:
    output = prepare()
    try:
        result = recognize(read_request())
    except (ImportError, importlib.metadata.PackageNotFoundError):
        emit(output, {"ok": False, "code": "runtime_unavailable"})
    except (Exception, SystemExit) as exc:
        print(f"DECIMER analysis failed type={type(exc).__name__}", file=sys.stderr)
        emit(output, {"ok": False, "code": "inference_failed"})
    else:
        emit(output, {"ok": True, "result": result})
    finally:
        output.close()


if __name__ == "__main__":
    main()
