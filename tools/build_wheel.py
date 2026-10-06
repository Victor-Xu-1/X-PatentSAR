"""Build only a fresh current-source snapshot; preserve old build directories."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from audit_wheel import audit
from wheel_sources import package_files, source_file

ROOT = Path(__file__).resolve().parents[1]


def stage(root: Path, work_root: Path) -> Path:
    inputs = package_files(root)
    work_root.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="x-patentsar-wheel-", dir=work_root))
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE", "NOTICE"):
        shutil.copy2(source_file(root, name), snapshot / name)
    for name, source in inputs.items():
        target = snapshot / "src" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if list(output.glob("*.whl")):
        parser.error("Output already contains a wheel; choose a new output directory")
    snapshot = stage(ROOT, args.work_root.resolve())
    command = [
        args.uv,
        "build",
        "--wheel",
        "--python",
        sys.executable,
        "--out-dir",
        str(output),
    ]
    if args.offline:
        command.append("--offline")
    subprocess.run(command, cwd=snapshot, check=True)
    wheels = list(output.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Fresh build did not produce exactly one wheel")
    result = audit(wheels[0], source_root=ROOT)
    print(
        json.dumps(
            {
                "wheel": str(wheels[0]),
                "snapshot": str(snapshot),
                "audit": result,
                "previous_build_directories_untouched": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
