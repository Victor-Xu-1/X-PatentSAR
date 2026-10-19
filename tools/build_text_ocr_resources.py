"""Generate the reviewed SDK inventory only from exact official wheel contents."""

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from patent_sar_extractor.core.text_ocr.identity import sdk_manifest


def build(wheels: Path, resources: Path) -> dict:
    recipe = json.loads((resources / "text-ocr-runtime.json").read_text())
    result = {}
    for spec in recipe["sdk_wheels"]:
        path = wheels / spec["file"]
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != spec["sha256"]:
            raise ValueError(
                "Text OCR wheel differs from the approved official artifact"
            )
        inventory = {}
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                relative = PurePosixPath(name)
                if relative.parts[0] != spec["prefix"] or name.endswith("/"):
                    continue
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or name.endswith(".pyc")
                ):
                    raise ValueError("Unsafe text OCR SDK wheel path")
                with archive.open(name) as stream:
                    sha = hashlib.file_digest(stream, "sha256").hexdigest()
                inventory[name] = sha
        if not 10 <= len(inventory) <= 8192:
            raise ValueError("Text OCR SDK inventory is missing or unbounded")
        result[spec["name"]] = inventory
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheels", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    resources = (
        Path(__file__).resolve().parents[1]
        / "src/patent_sar_extractor/defaults/environments"
    )
    target = resources / "text-ocr-sdk.json"
    if args.check:
        sdk_manifest(
            resources, json.loads((resources / "text-ocr-runtime.json").read_text())
        )
    if args.wheels is None:
        if not args.check:
            parser.error("Generation requires the exact approved --wheels directory")
        print(
            "Generated text OCR inventory fingerprint/path provenance verified; upstream wheel regeneration not requested."
        )
        raise SystemExit(0)
    text = json.dumps(build(args.wheels, resources), sort_keys=True, indent=2) + "\n"
    if args.check:
        if target.read_text() != text:
            raise SystemExit("Text OCR SDK inventory is stale")
        print("Generated text OCR inventory matches the approved upstream wheels.")
    else:
        target.write_text(text, encoding="utf-8")
