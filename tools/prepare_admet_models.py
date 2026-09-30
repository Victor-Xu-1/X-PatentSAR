"""Provision the official ADMET-AI 2.0.1 bundle without reference molecules.

The operator must provide a downloaded wheel and a destination. Nothing is
downloaded, existing unknown content is never replaced, and the manifest is
published last. This is an external-runtime tool, not a product dependency lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from patent_sar_extractor.workers.analysis_protocol import (  # noqa: E402
    ADMET_BUNDLE_SHA256,
    ADMET_VERSION,
    ADMET_WHEEL_SHA256,
)

SOURCE = "https://pypi.org/project/admet-ai/2.0.1/"
RESOURCE = "admet_ai/resources/"
LICENSE = "admet_ai-2.0.1.dist-info/licenses/LICENSE.txt"
MODEL_FILES = [
    "admet.csv",
    *(
        f"models/admet_{kind}/model_{i}.pt"
        for kind in ("classification", "regression")
        for i in range(5)
    ),
]
EXPECTED_FILES = {*MODEL_FILES, "LICENSE.txt", "manifest.json"}


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Input must be a regular file, not a link")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Input must be regular")
        result = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def fingerprint(entries: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": relative,
            "size": (root / relative).stat().st_size,
            "sha256": digest(root / relative),
        }
        for relative in sorted(MODEL_FILES)
    ]


def existing_bundle(root: Path) -> dict[str, Any]:
    paths = list(root.rglob("*"))
    if any(p.is_symlink() for p in paths):
        raise ValueError("Existing bundle contains a symbolic link")
    actual = {p.relative_to(root).as_posix() for p in paths if p.is_file()}
    if actual != EXPECTED_FILES:
        raise ValueError(
            "Existing destination contains unknown or incomplete content; preserve it and choose another destination"
        )
    manifest_path = root / "manifest.json"
    if manifest_path.stat().st_size > 64 * 1024:
        raise ValueError("Existing manifest exceeds its limit")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = inventory(root)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("name") != "ADMET-AI"
        or manifest.get("version") != ADMET_VERSION
        or manifest.get("wheel_sha256") != ADMET_WHEEL_SHA256
        or manifest.get("model_sha256") != ADMET_BUNDLE_SHA256
        or manifest.get("drugbank_reference") is not False
        or manifest.get("files") != entries
        or fingerprint(entries) != ADMET_BUNDLE_SHA256
    ):
        raise ValueError(
            "Existing bundle failed identity or content validation; it was not overwritten"
        )
    return manifest


def prepare(wheel: Path, model_dir: Path) -> dict[str, Any]:
    wheel = wheel.expanduser().absolute()
    destination = model_dir.expanduser().absolute()
    if wheel.stat().st_size > 32 * 1024 * 1024 or digest(wheel) != ADMET_WHEEL_SHA256:
        raise ValueError("Wheel does not match the official ADMET-AI 2.0.1 SHA-256")
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("Model destination and its parents must not be links")
    if any((p / ".git").exists() for p in (destination, *destination.parents)):
        raise ValueError("Models must remain outside source repositories")
    if destination.exists():
        if not destination.is_dir():
            raise ValueError("Existing model destination is not a directory")
        return existing_bundle(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".admet-provision-", dir=destination.parent
    ) as directory:
        temporary = Path(directory)
        with zipfile.ZipFile(wheel) as archive:
            for relative in [*MODEL_FILES, "LICENSE.txt"]:
                member = (
                    LICENSE
                    if relative == "LICENSE.txt"
                    else RESOURCE
                    + ("data/admet.csv" if relative == "admet.csv" else relative)
                )
                info = archive.getinfo(member)
                if info.is_dir() or info.file_size > 32 * 1024 * 1024:
                    raise ValueError(
                        "Upstream model member exceeds its allowed shape/size"
                    )
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
            entries = inventory(temporary)
            if fingerprint(entries) != ADMET_BUNDLE_SHA256:
                raise ValueError(
                    "Extracted model bundle differs from the reviewed official content"
                )
            manifest = {
                "schema_version": 1,
                "name": "ADMET-AI",
                "version": ADMET_VERSION,
                "source": SOURCE,
                "wheel_sha256": ADMET_WHEEL_SHA256,
                "license": "MIT",
                "drugbank_reference": False,
                "files": entries,
                "model_sha256": ADMET_BUNDLE_SHA256,
            }
        # mkdir is exclusive; a destination appearing during extraction is never replaced.
        destination.mkdir(mode=0o700, exist_ok=False)
        for relative in [*MODEL_FILES, "LICENSE.txt"]:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with (
                (temporary / relative).open("rb") as source,
                target.open("xb") as output,
            ):
                shutil.copyfileobj(source, output, 1024 * 1024)
        with (destination / "manifest.json").open("x", encoding="utf-8") as output:
            output.write(json.dumps(manifest, indent=2) + "\n")
        return existing_bundle(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheel",
        required=True,
        type=Path,
        help="Operator-downloaded official 2.0.1 wheel",
    )
    parser.add_argument(
        "--model-dir",
        required=True,
        type=Path,
        help="New external directory, or an identical verified bundle",
    )
    args = parser.parse_args()
    try:
        manifest = prepare(args.wheel, args.model_dir)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f"ADMET model provisioning failed: {error}\n")
    print(
        json.dumps(
            {
                "version": ADMET_VERSION,
                "model_sha256": manifest["model_sha256"],
                "model_files": 10,
                "drugbank_reference": False,
            }
        )
    )


if __name__ == "__main__":
    main()
