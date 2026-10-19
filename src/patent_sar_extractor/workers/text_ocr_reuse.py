"""Reuse a verified native runtime and snapshot existing pinned weights offline."""

from pathlib import Path

from patent_sar_extractor.core.text_ocr.identity import safe_file
from patent_sar_extractor.core.text_ocr.reuse_sources import validate_reuse_source
from patent_sar_extractor.web.environment_inspection import InspectionContext
from patent_sar_extractor.web.environment_specs import catalog_fingerprint

from .environment_errors import EnvironmentFailure
from .environment_files import atomic_json, checked_directory
from .text_ocr_setup import _copy_model, model_files, recipe


def reuse_existing_text_ocr(provisioner):
    plan = provisioner.plan
    source = validate_reuse_source(plan.reuse_source)
    reports, verified = [], {}
    for identifier in ("text-ocr", "text-ocr-models"):
        if identifier == "text-ocr-models":
            provisioner.progress("本地复制已验证的固定辅助文字权重；不下载")
            spec, models = recipe(), Path(source["models"])
            for item in spec["models"]:
                safe_file(models / item["file"])
            checked_directory(plan.install_root, private=True)
            prefix = plan.install_root / ("text-ocr-models-reused-" + plan.operation_id)
            prefix.mkdir(mode=0o700)
            target = prefix / "models"
            target.mkdir(mode=0o700)
            for item in spec["models"]:
                _copy_model(
                    models / item["file"],
                    target / item["file"],
                    item,
                    provisioner.cancel,
                )
                (target / item["file"]).chmod(0o600)
            model_files(target, spec)
            atomic_json(
                prefix,
                "receipt.json",
                {
                    "schema_version": 1,
                    "component_id": identifier,
                    "operation_id": plan.operation_id,
                    "catalog_sha256": catalog_fingerprint(),
                    "source_kind": "verified_local_copy",
                    "network_used": False,
                },
                limit=64 * 1024,
            )
            provisioner.bindings[identifier] = str(target)
        provisioner.progress(f"检测并复用现有组件 {identifier}")
        card = provisioner.inspect(
            [identifier],
            InspectionContext.from_bindings(provisioner.bindings),
            op_dir=plan.operation_dir,
            cancel=provisioner.cancel,
        )[0]
        if card.status != "ready":
            raise EnvironmentFailure("verification_failed")
        reports.append(card.model_dump(mode="json"))
        verified[identifier] = card.location
        provisioner.completed.append(identifier)
    provisioner.progress("现有辅助文字环境与本地权重均已验证；等待启用")
    return {
        "schema_version": 1,
        "operation_id": plan.operation_id,
        "components": reports,
        "bindings": verified,
    }
