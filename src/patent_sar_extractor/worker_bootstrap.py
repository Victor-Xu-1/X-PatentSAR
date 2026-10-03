"""Select only the calling first-party package, never a parent site-packages."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def bootstrap_package(package_root: Path) -> None:
    root = package_root.resolve(strict=True)
    existing = sys.modules.get("patent_sar_extractor")
    if existing is not None:
        location = getattr(existing, "__file__", None)
        if location and Path(location).resolve().parent == root:
            return
        raise ImportError(
            "A conflicting first-party package was loaded before the worker"
        )
    specification = importlib.util.spec_from_file_location(
        "patent_sar_extractor",
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    if specification is None or specification.loader is None:
        raise ImportError("The calling first-party worker package is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException:
        del sys.modules[specification.name]
        raise


if __name__ == "__main__":
    bootstrap_package(Path(__file__).resolve().parent)
