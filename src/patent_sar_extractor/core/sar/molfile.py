"""Inspect MDL semantics before RDKit can discard unsupported annotations."""

from __future__ import annotations

import re

from .errors import SARInputError
from .limits import MAX_ATOMS, MAX_BONDS, MAX_MOLFILE_BYTES


def _integer(text: str) -> int:
    try:
        return int(text.strip() or "0")
    except ValueError:
        raise SARInputError("invalid_molfile") from None


def _counts(atoms: int, bonds: int) -> None:
    if atoms < 1:
        raise SARInputError("empty_structure")
    if atoms > MAX_ATOMS or bonds > MAX_BONDS:
        raise SARInputError("structure_limit_exceeded")
    if bonds < 0:
        raise SARInputError("invalid_molfile")


def _bond(kind: int, stereo: int, *, v3000: bool) -> None:
    # Plain/wedged tetrahedral single bonds and crossed unknown double bonds
    # are supported. Wavy singles, query bonds and special stereo are not.
    single = {0, 1, 3} if v3000 else {0, 1, 6}
    double = {0, 2} if v3000 else {0, 3}
    allowed = {1: single, 2: double, 3: {0}, 4: {0}}
    if kind not in allowed:
        raise SARInputError("unsupported_bond")
    if stereo not in allowed[kind]:
        raise SARInputError("unsupported_mdl_stereo")


def _v2000(lines: list[str]) -> None:
    atoms, bonds = _integer(lines[3][:3]), _integer(lines[3][3:6])
    _counts(atoms, bonds)
    if len(lines) < 5 + atoms + bonds:
        raise SARInputError("invalid_molfile")
    for line in lines[4 : 4 + atoms]:
        # RDKit does not reliably interpret standalone MDL atom parity.
        if _integer(line[39:42]):
            raise SARInputError("unsupported_mdl_atom_parity")
    for line in lines[4 + atoms : 4 + atoms + bonds]:
        _bond(_integer(line[6:9]), _integer(line[9:12]), v3000=False)
    for line in lines[4 + atoms + bonds :]:
        if line.strip() and not line.startswith(
            ("M  CHG", "M  ISO", "M  RAD", "M  END")
        ):
            raise SARInputError("unsupported_molfile_annotation")


def _v3000(lines: list[str]) -> None:
    section = ""
    for line in lines[4:]:
        if line == "M  END" or not line.strip():
            continue
        if not line.startswith("M  V30 ") or line.endswith("-"):
            raise SARInputError("unsupported_molfile_annotation")
        content = line[7:]
        fields = content.split()
        if content.startswith("BEGIN "):
            section = content[6:]
            if section not in {"CTAB", "ATOM", "BOND", "COLLECTION"}:
                raise SARInputError("unsupported_molfile_annotation")
        elif content.startswith("END "):
            section = ""
        elif content.startswith("COUNTS "):
            if len(fields) != 6:
                raise SARInputError("invalid_molfile")
            _counts(_integer(fields[1]), _integer(fields[2]))
            if any(_integer(field) for field in fields[3:]):
                raise SARInputError("unsupported_molfile_annotation")
        elif section == "COLLECTION":
            if not re.fullmatch(r"MDLV30/STEABS ATOMS=\([0-9 ]+\)", content):
                raise SARInputError("unsupported_mdl_stereo")
        elif section in {"ATOM", "BOND"}:
            allowed = {"CHG", "RAD", "MASS", "CFG"} if section == "ATOM" else {"CFG"}
            attributes = re.findall(r"([A-Z][A-Z0-9_]*)=([^ ]+)", content)
            if any(key not in allowed for key, _ in attributes):
                raise SARInputError("unsupported_molfile_annotation")
            cfg = next(
                (_integer(value) for key, value in attributes if key == "CFG"), 0
            )
            if section == "ATOM" and cfg:
                raise SARInputError("unsupported_mdl_atom_parity")
            if section == "BOND":
                if len(fields) < 4:
                    raise SARInputError("invalid_molfile")
                _bond(_integer(fields[1]), cfg, v3000=True)
        else:
            raise SARInputError("unsupported_molfile_annotation")


def inspect_molfile(raw: object) -> str:
    """Return exact input bytes-as-text, or raise only a safe error code."""
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise SARInputError("invalid_molfile")
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeError:
        raise SARInputError("invalid_molfile") from None
    if size > MAX_MOLFILE_BYTES:
        raise SARInputError("molfile_limit_exceeded")
    lines = raw.splitlines()
    if len(lines) < 5 or lines.count("M  END") != 1:
        raise SARInputError("invalid_molfile")
    if any(line.strip() for line in lines[lines.index("M  END") + 1 :]):
        raise SARInputError("multiple_molfile_documents")
    if re.search(r"\b3D\b", lines[1]):
        raise SARInputError("unsupported_molfile_3d")
    if lines[3].endswith("V2000"):
        _v2000(lines)
    elif lines[3].endswith("V3000"):
        _v3000(lines)
    else:
        raise SARInputError("unsupported_molfile_format")
    return raw
