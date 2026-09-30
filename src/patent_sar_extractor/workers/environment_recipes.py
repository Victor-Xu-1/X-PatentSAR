"""Six fixed recipes. New prefixes are exclusive; configured paths are read-only."""

from __future__ import annotations

import shutil
import sys
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path

from patent_sar_extractor.web.environment_models import (
    ComponentId,
    EnvironmentComponent,
)
from patent_sar_extractor.web.environment_specs import (
    ADMET_WHEEL_SHA256,
    ADMET_WHEEL_URL,
    UV_BINARY_SHA256,
    UV_VERSION,
    UV_WHEEL_SHA256,
    UV_WHEEL_URL,
    catalog_fingerprint,
    component_spec,
    recipe_path,
    resolved_components,
)

from .admet_models import prepare
from .environment_assets import download, extract_model_group
from .environment_commands import install_environment, run_command
from .environment_errors import EnvironmentFailure
from .environment_files import atomic_json, checked_directory, file_sha256, load_json
from .environment_plan import EnvironmentPlan


class EnvironmentProvisioner:
    def __init__(
        self,
        plan: EnvironmentPlan,
        cancel: threading.Event,
        inspect: Callable[..., list[EnvironmentComponent]],
    ) -> None:
        self.plan = plan
        self.cancel = cancel
        self.inspect = inspect
        self.bindings = dict(plan.bindings)
        self.completed: list[ComponentId] = []
        self.env = install_environment(plan.cache_root, plan.operation_dir)

    def progress(self, stage: str) -> None:
        if self.cancel.is_set():
            raise InterruptedError("Operation cancelled")
        atomic_json(
            self.plan.operation_dir,
            "environment-progress.json",
            {"stage": stage, "completed_components": self.completed},
            limit=64 * 1024,
        )
        print(stage, flush=True)  # Fixed, bounded stage text; no SDK output/secrets.

    def execute(self) -> dict[str, object]:
        from patent_sar_extractor.web.environment_inspection import InspectionContext

        ids = (
            resolved_components(self.plan.component_ids)
            if self.plan.action == "install"
            else self.plan.component_ids
        )
        reports = []
        verified = {}
        additional = {}
        for identifier in ids:
            self.progress(f"检查组件 {identifier}")
            card = self.inspect(
                [identifier],
                InspectionContext.from_bindings(self.bindings),
                op_dir=self.plan.operation_dir,
                cancel=self.cancel,
            )[0]
            if self.plan.action == "install" and card.status != "ready":
                self.progress(f"安装固定组件 {identifier} 至新的专属前缀")
                self.bindings[identifier] = str(self.install(identifier))
                self.progress(f"验证新组件 {identifier}")
                card = self.inspect(
                    [identifier],
                    InspectionContext.from_bindings(self.bindings),
                    op_dir=self.plan.operation_dir,
                    cancel=self.cancel,
                )[0]
                if card.status != "ready":
                    raise EnvironmentFailure(
                        "verification_failed",
                        [
                            f"error: check={c.name}: {c.message}"
                            for c in card.checks
                            if not c.ok
                        ],
                    )
            if card.status == "ready":
                assert card.location is not None
                verified[identifier] = card.location
                if identifier == "decimer-models":
                    python = self.bindings["decimer"]
                    additional.update(
                        segmentation_config(
                            Path(card.location), Path(python) if python else None
                        )
                    )
            reports.append(card.model_dump(mode="json"))
            self.completed.append(identifier)
        self.progress("实际组件验证完成；等待主进程决定是否启用")
        result: dict[str, object] = {
            "schema_version": 1,
            "operation_id": self.plan.operation_id,
            "components": reports,
            "bindings": verified,
        }
        if additional:
            result["additional_config"] = additional
        return result

    def install(self, identifier: ComponentId) -> Path:
        if self.cancel.is_set():
            raise InterruptedError("Operation cancelled")
        version = {
            "installer": UV_VERSION,
            "base": "py312",
            "decimer": "2.8.0-py31020",
            "decimer-models": "v2-seg1.5.0",
            "admet": "2.0.1-cpu",
            "admet-models": "2.0.1",
        }[identifier]
        prefix = (
            self.plan.install_root / f"{identifier}-{version}-{self.plan.operation_id}"
        )
        checked_directory(self.plan.install_root, private=True)
        prefix.mkdir(mode=0o700, exist_ok=False)
        if identifier == "installer":
            binding = self._installer(prefix)
        elif identifier in {"base", "admet", "decimer"}:
            binding = self._runtime(identifier, prefix)
        elif identifier == "admet-models":
            wheel = download(
                ADMET_WHEEL_URL,
                self.plan.cache_root,
                size=14311533,
                sha256=ADMET_WHEEL_SHA256,
                cancel=self.cancel,
                progress=self.download_progress,
            )
            binding = prefix / "models"
            prepare(wheel, binding)
        else:
            binding = self._decimer_models(prefix)
        # This receipt is provenance, not a completion/activation flag. The result
        # file is written only after loaded-model/interpreter verification passes.
        atomic_json(
            prefix,
            "receipt.json",
            {
                "schema_version": 1,
                "component_id": identifier,
                "operation_id": self.plan.operation_id,
                "catalog_sha256": catalog_fingerprint(),
            },
            limit=64 * 1024,
        )
        return binding

    def _installer(self, prefix: Path) -> Path:
        wheel = download(
            UV_WHEEL_URL,
            self.plan.cache_root,
            size=26894006,
            sha256=UV_WHEEL_SHA256,
            cancel=self.cancel,
            progress=self.download_progress,
        )
        with zipfile.ZipFile(wheel) as source:
            members = [
                i for i in source.infolist() if i.filename.endswith(".data/scripts/uv")
            ]
            if len(members) != 1 or members[0].file_size > 128 * 1024 * 1024:
                raise ValueError("Official uv wheel has an unexpected binary layout")
            target = prefix / "uv"
            with source.open(members[0]) as stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output, 1024 * 1024)
        if file_sha256(target, limit=128 * 1024 * 1024) != UV_BINARY_SHA256:
            raise ValueError("Owned uv binary SHA-256 differs")
        target.chmod(0o700)
        return target

    def _runtime(self, identifier: ComponentId, prefix: Path) -> Path:
        spec = component_spec(identifier)
        if spec.requirements is None or not recipe_path(spec.requirements).is_file():
            raise ValueError("Canonical packaged requirements are missing")
        installer = self.bindings["installer"]
        if (
            installer is None
            or file_sha256(Path(installer), limit=128 * 1024 * 1024) != UV_BINARY_SHA256
        ):
            raise ValueError("A verified owned installer is required")
        python = Path(sys.executable)
        if identifier == "decimer":
            # uv's pinned release carries the official python-build-standalone
            # source/checksum table. No custom mirror/URL or global registration.
            managed = prefix / "python"
            self._command(
                [
                    installer,
                    "python",
                    "install",
                    "3.10.20",
                    "--install-dir",
                    str(managed),
                    "--no-bin",
                    "--no-registry",
                ]
            )
            candidates = list(
                managed.glob("cpython-3.10.20-linux-x86_64-gnu/bin/python3.10")
            )
            if len(candidates) != 1:
                raise ValueError("Pinned managed Python executable was not found")
            python = candidates[0]
        runtime = prefix / "venv"
        self._command(
            [
                installer,
                "venv",
                "--no-python-downloads",
                "--python",
                str(python),
                str(runtime),
            ]
        )
        binding = runtime / "bin/python"
        command = [
            installer,
            "pip",
            "sync",
            "--python",
            str(binding),
            "--require-hashes",
            "--no-build",
            "--index-url",
            "https://pypi.org/simple",
            str(recipe_path(spec.requirements)),
        ]
        if identifier == "admet":
            command.extend(["--torch-backend", "cpu"])
        self._command(command)
        self._command([installer, "pip", "check", "--python", str(binding)])
        return binding

    def _command(self, command: list[str]) -> None:
        run_command(
            command,
            operation_dir=self.plan.operation_dir,
            env=self.env,
            cancel=self.cancel,
        )

    def _decimer_models(self, prefix: Path) -> Path:
        recipe = load_json(recipe_path("decimer-models.json"))
        root = prefix / "models"
        root.mkdir(mode=0o700)
        for group in recipe["ocsrc"]:
            self.progress("下载并核对官方 OCSR 模型及成员 SHA-256")
            archive = download(
                group["url"],
                self.plan.cache_root,
                size=group["download_bytes"],
                md5=group["md5"],
                cancel=self.cancel,
                progress=self.download_progress,
            )
            extract_model_group(archive, root, group, self.cancel)
        segment = recipe["segmentation"]
        self.progress("下载并核对官方分割权重 SHA-256")
        asset = download(
            segment["url"],
            self.plan.cache_root,
            size=segment["download_bytes"],
            sha256=segment["sha256"],
            md5=segment["md5"],
            cancel=self.cancel,
            progress=self.download_progress,
        )
        target = root / "segmentation/mask_rcnn_molecule.h5"
        target.parent.mkdir(mode=0o700)
        with asset.open("rb") as source, target.open("xb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
        return root

    def download_progress(self, received: int, total: int) -> None:
        self.progress(f"官方资源下载：{received} / {total} bytes（完成后仍须核验内容）")


def segmentation_config(
    model_root: Path, decimer_python: Path | None = None
) -> dict[str, str]:
    """Called after readiness; select verified bundled or read-only legacy H5."""
    from .environment_segmentation import SEGMENTATION_SHA256

    weights = model_root / "segmentation/mask_rcnn_molecule.h5"
    if not weights.exists():
        if decimer_python is None:
            return {}
        # The selected, actually checked Python 3.10 environment's package-local
        # official cache is read-only. Never relocate or write into that env.
        weights = (
            decimer_python.parent.parent
            / "lib/python3.10/site-packages/decimer_segmentation/mask_rcnn_molecule.h5"
        )
        if not weights.exists():
            raise ValueError(
                "Loaded legacy segmentation path could not be derived safely"
            )
    if file_sha256(weights) != SEGMENTATION_SHA256:
        raise ValueError("Segmentation binding changed before publication")
    return {"decimer_segmentation_models": str(weights)}
