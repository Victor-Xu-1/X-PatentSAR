"""Verify standalone wheel identity, static bundle integrity and file hygiene."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from wheel_sources import package_files, verify_package_files

from patent_sar_extractor.contracts import DISTRIBUTION_NAME, __version__


def audit(wheel: Path, *, source_root: Path | None = None) -> dict[str, object]:
    expected_sources = package_files(source_root or Path(__file__).resolve().parents[1])
    dist_info = f"{DISTRIBUTION_NAME.replace('-', '_')}-{__version__}.dist-info/"
    package = "patent_sar_extractor/"
    static = package + "web/static/"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Wheel contains duplicate entries")
        source_count = verify_package_files(archive, expected_sources)
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename:
                raise ValueError("Wheel contains an unsafe path")
            if not item.filename.startswith((package, dist_info)):
                raise ValueError(f"Unexpected package root: {item.filename}")
            if stat.S_IFMT(item.external_attr >> 16) == stat.S_IFLNK:
                raise ValueError("Wheel contains a symbolic link")
            if any(
                part in {"__pycache__", "node_modules", ".env"} for part in path.parts
            ):
                raise ValueError("Wheel contains runtime or development files")
            if (
                path.suffix
                in {
                    ".pdf",
                    ".h5",
                    ".pt",
                    ".ckpt",
                    ".pyc",
                    ".sqlite",
                    ".sqlite3",
                    ".xlsx",
                    ".sdf",
                    ".log",
                }
                or ".local.yaml" in item.filename
            ):
                raise ValueError(
                    "Wheel contains private or scientific runtime artifacts"
                )
            if path.suffix == ".png" and not item.filename.startswith(static):
                raise ValueError(
                    "Wheel contains a scientific image outside the UI bundle"
                )
        metadata = BytesParser().parsebytes(archive.read(dist_info + "METADATA"))
        if metadata["Name"] != DISTRIBUTION_NAME or metadata["Version"] != __version__:
            raise ValueError("Wheel product identity differs from contracts.py")
        if metadata["License-Expression"] != "Apache-2.0":
            raise ValueError("Wheel first-party license is not Apache-2.0")
        if archive.read(dist_info + "top_level.txt").strip() != b"patent_sar_extractor":
            raise ValueError("Wheel contains a competing Python namespace")
        for license_name in ("LICENSE", "NOTICE"):
            if not archive.read(dist_info + "licenses/" + license_name).strip():
                raise ValueError("Wheel is missing license or attribution text")
        resources = package + "defaults/environments/"
        for recipe in (
            "base-requirements.txt",
            "base-runtime.json",
            "admet-cpu-requirements.txt",
            "decimer-inputs.txt",
            "decimer-requirements.txt",
            "decimer-models.json",
        ):
            if not archive.read(resources + recipe).strip():
                raise ValueError("Wheel is missing a managed environment recipe")
        base = json.loads(archive.read(resources + "base-runtime.json"))
        if (
            base.get("schema_version") != 1
            or base.get("generator") != "tools/build_environment_resources.py"
            or hashlib.sha256(
                archive.read(resources + "base-requirements.txt")
            ).hexdigest()
            != base.get("requirements_sha256")
        ):
            raise ValueError("Wheel base environment recipe provenance failed")
        marker = json.loads(archive.read(static + ".bundle.json"))
        if marker.get("generator") != "tools/build_frontend.py" or not isinstance(
            marker.get("files"), dict
        ):
            raise ValueError("Wheel Web bundle provenance is missing")
        expected = marker["files"]
        actual = {
            name[len(static) :]
            for name in names
            if name.startswith(static) and name != static + ".bundle.json"
        }
        if (
            set(expected) != actual
            or "index.html" not in actual
            or not any(name.endswith(".js") for name in actual)
        ):
            raise ValueError(
                "Wheel Web asset collection differs from its build manifest"
            )
        for relative, digest in expected.items():
            if hashlib.sha256(archive.read(static + relative)).hexdigest() != digest:
                raise ValueError("Wheel Web asset checksum failed")
        return {
            "product": DISTRIBUTION_NAME,
            "version": __version__,
            "file_count": len(names),
            "web_asset_count": len(actual),
            "source_files_matched": source_count,
            "passed": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.wheel, source_root=args.source_root)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Wheel audit failed: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
