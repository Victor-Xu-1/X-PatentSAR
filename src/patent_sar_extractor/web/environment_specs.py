"""Single fixed component catalog for local, CPU-only environment recipes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from .environment_models import ComponentId, EnvironmentComponent

UV_VERSION = "0.11.31"
UV_WHEEL_URL = "https://files.pythonhosted.org/packages/c4/c3/019ecbf3564d909c55fcf065592aff90b8b386d679e379caf356de4473f9/uv-0.11.31-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
UV_WHEEL_SHA256 = "44ac79fca5807122676701279a1f36d7917a922f25a0ab5c5cf58a252f666e7e"
UV_BINARY_SHA256 = "007b99a549b25f668d503535f4b1e21e3f34111318fd79bea50fada64f65eb9d"
ADMET_WHEEL_URL = "https://files.pythonhosted.org/packages/12/19/5d83e84207636e6dd655b7cefab95c04eb5a48e7eaa1151424370b1a6ff1/admet_ai-2.0.1-py3-none-any.whl"
ADMET_WHEEL_SHA256 = "fef3527f637abb00d272cf824e8eef0136fe31ebde6c56881f1a8c02c0417806"


@dataclass(frozen=True)
class ComponentSpec:
    id: ComponentId
    name: str
    description: str
    version: str
    kind: Literal["tool", "runtime", "models"]
    group: Literal["tools", "base", "structure", "admet"]
    required: bool
    license: str
    source_url: str
    dependencies: tuple[ComponentId, ...] = ()
    requirements: str | None = None
    download_bytes: int | None = None


_SPECS = (
    ComponentSpec(
        "installer",
        "受管安装工具",
        "本软件专属 uv；不依赖或修改全局工具。",
        UV_VERSION,
        "tool",
        "tools",
        True,
        "MIT OR Apache-2.0",
        "https://github.com/astral-sh/uv/releases/tag/0.11.31",
        download_bytes=26894006,
    ),
    ComponentSpec(
        "base",
        "基础提取环境",
        "单一 Python 3.12 PDF、RapidOCR 和 RDKit 运行环境。",
        "Python 3.12 / pinned application runtime",
        "runtime",
        "base",
        True,
        "Mixed; PyMuPDF AGPL/commercial, see NOTICE",
        "https://github.com/Victor-Xu-1/X-PatentSAR",
        ("installer",),
        "base-requirements.txt",
    ),
    ComponentSpec(
        "decimer",
        "DECIMER 结构环境",
        "Python 3.10.20 / DECIMER 2.8.0 / Segmentation 1.5.0 / TF 2.15.1 / NumPy 1.26.4，强制 CPU。",
        "2.8.0 / 1.5.0",
        "runtime",
        "structure",
        True,
        "MIT; TensorFlow Apache-2.0; segmentation weights CC-BY-4.0",
        "https://pypi.org/project/decimer/2.8.0/",
        ("installer",),
        "decimer-requirements.txt",
    ),
    ComponentSpec(
        "decimer-models",
        "DECIMER 模型权重",
        "真实 OCSR、手绘 OCSR 和分割权重；加载检查不能替代识别准确性验收。",
        "OCSR V2 + segmentation 1.5.0",
        "models",
        "structure",
        True,
        "CC-BY-4.0",
        "https://zenodo.org/records/8300489",
        ("decimer",),
        download_bytes=869827745,
    ),
    ComponentSpec(
        "admet",
        "ADMET CPU 环境",
        "独立 Python 3.12 / ADMET-AI 2.0.1 / Chemprop 2 / CPU Torch；不是实验测量。",
        "2.0.1",
        "runtime",
        "admet",
        False,
        "MIT and mixed dependencies; PaDEL AGPL/LGPL, see NOTICE",
        "https://pypi.org/project/admet-ai/2.0.1/",
        ("installer",),
        "admet-cpu-requirements.txt",
    ),
    ComponentSpec(
        "admet-models",
        "ADMET 模型权重",
        "十个官方 pt 模型及端点元数据；不复制或使用 DrugBank 参考集。",
        "2.0.1",
        "models",
        "admet",
        False,
        "MIT",
        "https://github.com/swansonk14/admet_ai",
        ("admet",),
        download_bytes=14311533,
    ),
)


def component_specs() -> tuple[ComponentSpec, ...]:
    return _SPECS


def component_catalog() -> list[dict[str, Any]]:
    """Metadata only: a GET/catalog never imports SDKs or downloads models."""
    return [
        EnvironmentComponent(
            id=spec.id,
            name=spec.name,
            description=spec.description,
            version=spec.version,
            detected_version=None,
            status="unchecked",
            location=None,
            kind=spec.kind,
            group=spec.group,
            required=spec.required,
            installable=spec.requirements is None
            or recipe_path(spec.requirements).is_file(),
            download_bytes=spec.download_bytes,
            installed_bytes=None,
            license=spec.license,
            source_url=spec.source_url,
            checks=[],
            problem=None,
        ).model_dump(mode="json")
        for spec in _SPECS
    ]


def component_spec(component_id: str) -> ComponentSpec:
    for spec in _SPECS:
        if spec.id == component_id:
            return spec
    raise ValueError("Component is outside the environment allowlist")


def recipe_path(name: str) -> Path:
    if name not in {
        "base-requirements.txt",
        "admet-cpu-requirements.txt",
        "decimer-requirements.txt",
        "decimer-models.json",
    }:
        raise ValueError("Unknown packaged recipe")
    return Path(
        str(files("patent_sar_extractor.defaults").joinpath("environments", name))
    )


def catalog_fingerprint() -> str:
    recipes = {}
    for name in sorted(
        {s.requirements for s in _SPECS if s.requirements} | {"decimer-models.json"}
    ):
        path = recipe_path(name)
        recipes[name] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    return hashlib.sha256(
        json.dumps(
            {"catalog": [asdict(s) for s in _SPECS], "recipes": recipes},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def resolved_components(component_ids: list[ComponentId]) -> list[ComponentId]:
    result: list[ComponentId] = []

    def visit(component_id: ComponentId) -> None:
        spec = component_spec(component_id)
        for dependency in spec.dependencies:
            visit(dependency)
        if component_id not in result:
            result.append(component_id)

    for component_id in component_ids:
        visit(component_id)
    return result
