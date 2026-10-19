"""Conservative header typography, never a value or scientific-identity repair."""

from __future__ import annotations

import re
from collections import Counter

# Only long, explicit potency endpoints may follow an OCR-concatenated label.
# Short names (CL, F, Ki, ...) retain lexical boundaries to avoid gene/prose hits.
METRIC = re.compile(
    r"(?:(?:p?IC50|EC50|DC50|GI50|CC50)(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])(?:Ki|Kd|Imax|Dmax|Ymin|Ymax|Clint|CL|t1/2|Cmax|"
    r"AUC(?:0?(?:-|–)?(?:t|inf))?|TGI|Dose|Tumou?r\s+volume|p\s*value|"
    r"Ratio|Grade|F)(?![A-Za-z0-9]))"
    r"\s*(?:\([^)]*\)|（[^）]*）)?(?:\s+(?:grade|class))?",
    re.IGNORECASE,
)
UNITLESS = re.compile(r"^(?:p\s*value|Ratio|Grade|Ymin|Ymax)$", re.IGNORECASE)
_POTENCY = re.compile(
    r"(?:pI[\s_]*C|(?<![A-Za-z0-9])p[\s_]+I[\s_]*C|I[\s_]*C|E[\s_]*C|"
    r"D[\s_]*C|G[\s_]*I|C[\s_]*C)[\s_]*5[\s_]*[0O]"
    r"(?=[fpnumµμ]?M(?![A-Za-z0-9])|[^A-Za-z0-9]|$)",
    re.IGNORECASE,
)
_SHORT = re.compile(
    r"(?<![A-Za-z0-9])(?:K[\s_]*[id]|[IDY][\s_]*m[\s_]*a[\s_]*x|"
    r"Y[\s_]*m[\s_]*i[\s_]*n|C[\s_]*m[\s_]*a[\s_]*x|"
    r"C[\s_]*L[\s_]*i[\s_]*n[\s_]*t)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_SPELLINGS = {
    name.lower(): name
    for name in ("Ki", "Kd", "Imax", "Dmax", "Ymin", "Ymax", "Cmax", "Clint")
}
_UNIT = re.compile(
    r"[fpnumµμ]?M|%|(?:[pnumµμ]?g)/(?:kg|[munµμ]?L)|"
    r"(?:mL|L)/(?:min|h)(?:/kg)?|(?:mm|cm)(?:3|\^3)|h|min|s",
)
_PARENS = re.compile(r"\(([^()]*)\)")
_GLYPHS = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹（）", "01234567890123456789()")
_LITERAL_UNIT = re.compile(rf"(?<![A-Za-z0-9])(?:{_UNIT.pattern})(?![A-Za-z0-9])")


def explicit_unit(text: str) -> str | None:
    """A whole unit fragment, not a guessed unit from a caption or assay name."""
    clean = text.strip().strip("()（ ）")
    compact = re.sub(r"\s+", "", clean)
    return compact if _UNIT.fullmatch(compact) else None


def literal_header_units(text: str) -> set[str]:
    """Complete printed header units with lexical boundaries, not defaults."""
    normalized = normalize_metric_text(text)
    return {
        match.group().replace("µ", "u").replace("μ", "u")
        for match in _LITERAL_UNIT.finditer(normalized)
    }


def header_qualifier_text(text: str) -> str:
    """Comparison-only non-unit observations; no endpoint/value interpretation.

    Units have their own per-endpoint guard. Ignore only those exact unit
    tokens and wrappers left empty by them, not numbers, timing words,
    construct annotations or unknown strings.
    """
    literal = _LITERAL_UNIT.sub(" ", normalize_metric_text(text))
    return re.sub(r"\(\s*\)", " ", literal).strip()


def normalize_metric_text(text: str) -> str:
    """Normalize typography in headers only; callers retain the original text."""
    text = str(text or "").translate(_GLYPHS)

    def potency(match: re.Match[str]) -> str:
        compact = re.sub(r"[\s_]", "", match.group()).upper().replace("O", "0")
        name = "pIC50" if compact == "PIC50" else compact
        prefix = " " if match.start() and text[match.start() - 1].isalnum() else ""
        # A literal complete molar unit may touch the printed endpoint. Insert
        # only its separator, never infer a unit or rewrite measurement values.
        suffix = (
            " " if re.match(r"[fpnumµμ]?M(?![A-Za-z0-9])", text[match.end() :]) else ""
        )
        return prefix + name + suffix

    text = _POTENCY.sub(potency, text)
    text = _SHORT.sub(
        lambda m: _SPELLINGS[re.sub(r"[\s_]", "", m.group()).lower()], text
    )
    text = _PARENS.sub(
        lambda m: f"({explicit_unit(m.group(1)) or m.group(1).strip()})", text
    )
    # A complete separate unit fragment uses the existing whole-unit grammar,
    # including its transparent wrappers. Original observations remain verbatim.
    pieces = text.splitlines()
    for index, piece in enumerate(pieces):
        unit = explicit_unit(piece)
        if unit:
            pieces[index] = f"({unit})"
    return "\n".join(pieces)


def label_with_suffix(key: str, suffix: str) -> str:
    """Keep units terminal for the existing schema-v1 projection consumers."""
    unit = re.search(r"\s*(\([^()]+\))$", key)
    if unit:
        return f"{key[: unit.start()].rstrip()} {suffix} {unit.group(1)}"
    return f"{key} {suffix}"


def distinct_value_keys(keys: list[str]) -> list[str]:
    """Stable group-relative physical ordinals; no raw field may overwrite another."""
    counts = Counter(keys)
    reserved, used = set(keys) | {"compound_id"}, {"compound_id"}
    result = []
    for index, key in enumerate(keys, start=1):
        candidate = key
        if counts[key] > 1 or candidate in used:
            candidate = label_with_suffix(key, f"[column {index}]")
            collision = 2
            while candidate in reserved or candidate in used:
                candidate = label_with_suffix(key, f"[column {index}; {collision}]")
                collision += 1
        result.append(candidate)
        used.add(candidate)
    return result
