"""Pure operator-source contract; mounted models are input, never executables."""

from pathlib import Path

TEXT_OCR_PAIR = frozenset({"text-ocr", "text-ocr-models"})


def validate_reuse_source(value):
    if not isinstance(value, dict) or set(value) != {"python", "models"}:
        raise ValueError(
            "Existing text OCR requires exactly an interpreter and model directory"
        )
    for key, raw in value.items():
        if (
            not isinstance(raw, str)
            or not 1 <= len(raw) <= 512
            or not Path(raw).is_absolute()
            or Path(raw) == Path("/")
            or str(Path(raw)) != raw
            or "\\" in raw
            or ":" in raw
            or any(ord(character) < 32 or ord(character) == 127 for character in raw)
            or any(part in {".", ".."} for part in raw.split("/"))
            or key == "python"
            and Path(raw).is_relative_to("/mnt")
        ):
            raise ValueError("Existing text OCR source path is invalid")
    return dict(value)


def reuse_plan_source(plan):
    source = plan.get("reuse_source")
    if plan.get("action") != "reuse":
        if source is not None:
            raise ValueError("Only reuse operations may carry existing sources")
        return None
    if set(plan.get("component_ids", [])) != TEXT_OCR_PAIR:
        raise ValueError("Text OCR reuse must verify its complete runtime/model pair")
    source = validate_reuse_source(source)
    if plan.get("bindings", {}).get("text-ocr") != source["python"]:
        raise ValueError("Existing interpreter differs from the captured reuse plan")
    return source
