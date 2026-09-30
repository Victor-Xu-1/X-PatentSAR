"""Bounded adapter around the existing single-wrapper, never a second OCSR engine."""

from __future__ import annotations

import importlib.metadata
import io
import json
import runpy
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
from patent_sar_extractor.workers.analysis_protocol import (  # noqa: E402
    emit,
    prepare,
    read_request,
)


class BoundedCapture(io.StringIO):
    def write(self, value: str) -> int:
        if self.tell() + len(value) > 64 * 1024:
            raise ValueError("DECIMER wrapper output exceeds its limit")
        return super().write(value)


def recognize(request: dict[str, object]) -> dict[str, object]:
    version = importlib.metadata.version("DECIMER")
    if set(request) != {"image_path"} or not isinstance(request["image_path"], str):
        raise ValueError("Invalid recognition request")
    image = Path(request["image_path"])
    if (
        image.is_symlink()
        or not image.is_file()
        or image.stat().st_size > 16 * 1024 * 1024
    ):
        raise ValueError("Invalid bounded crop")
    wrapper = Path(__file__).resolve().parents[1] / "core/ocsr/wrapper_decimer.py"
    sys.argv = [str(wrapper), str(image)]
    with BoundedCapture() as capture, redirect_stdout(capture):
        namespace = runpy.run_path(str(wrapper), run_name="__analysis_single_wrapper__")
        namespace["main"]()
        payload = json.loads(capture.getvalue())
    if not isinstance(payload, dict):
        raise ValueError("Invalid wrapper protocol")
    if payload.get("status") == "success":
        smiles = payload.get("smiles")
        if not isinstance(smiles, str) or len(smiles) > 2048:
            raise ValueError("Invalid wrapper SMILES")
    elif payload.get("error") == "DECIMER returned empty SMILES":
        smiles = None
    else:
        raise ValueError("DECIMER model failed")
    return {"raw_smiles": smiles, "engine": {"name": "DECIMER", "version": version}}


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
