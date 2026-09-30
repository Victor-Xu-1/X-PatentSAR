"""Prepare the official ADMET bundle; implementation is shared with the worker."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from patent_sar_extractor.workers.admet_models import (  # noqa: F401
    ADMET_BUNDLE_SHA256,
    ADMET_VERSION,
    ADMET_WHEEL_SHA256,
    EXPECTED_FILES,
    MODEL_FILES,
    digest,
    existing_bundle,
    fingerprint,
    inventory,
    prepare,
)


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
