"""Bounded generated-token completion, not a chemical-correctness or confidence claim."""

import re

MAX_GENERATION_TOKENS = 1024
MAX_GENERATION_TEXT = 12000
FIELDS = {"version", "tokens", "status", "reason"}
# The installed DECIMER utils.decoder digit alphabet. This is a readback
# invariant, not another molecule writer; the adapter still calls that SDK.
_DIGITS = str.maketrans("!$^<>?£¢€§", "1234567890")
_NON_ASCII = frozenset("£¢€§")


def observe_generation(words):
    """Keep every token, removing only actual outer sentinels from codec input.

    In particular, a parseable prefix without <end> is incomplete; internal
    control tokens cannot be erased into a different apparent molecule.
    """
    if (
        not isinstance(words, list)
        or not 1 <= len(words) <= MAX_GENERATION_TOKENS
        or any(
            not isinstance(word, str)
            or not 1 <= len(word) <= 32
            or any(not char.isascii() and char not in _NON_ASCII for char in word)
            or not word.isprintable()
            for word in words
        )
        or sum(map(len, words)) > MAX_GENERATION_TEXT
    ):
        raise ValueError("DECIMER returned an invalid bounded token sequence")
    start = int(words[0] == "<start>")
    stop = len(words) - int(words[-1] == "<end>")
    content = words[start:stop]
    reason = (
        "missing_start"
        if not start
        else "missing_end"
        if stop == len(words)
        else "empty_content"
        if not content
        else "unexpected_special"
        if any(re.fullmatch(r"<[^>]*>", word) for word in content)
        else None
    )
    return (
        "".join(content),
        {
            "version": 1,
            "tokens": list(words),
            "status": "complete" if reason is None else "incomplete",
            "reason": reason,
        },
        (start, stop),
    )


def validate_generation(packet):
    """Replay the token grammar; self-attested complete/reason flags grant nothing."""
    if (
        not isinstance(packet, dict)
        or set(packet) != FIELDS
        or type(packet["version"]) is not int
        or packet["version"] != 1
    ):
        raise ValueError("Malformed DECIMER generation observation")
    _encoded, expected, _slice = observe_generation(packet["tokens"])
    if packet != expected:
        raise ValueError("DECIMER completion differs from the retained tokens")
    return packet["status"] == "complete"


def complete_generation(packet):
    try:
        return validate_generation(packet)
    except (TypeError, ValueError):
        return False


def validate_generation_observation(packet, raw):
    """Recheck literal SDK decoding, preserving valid incomplete observations."""
    complete = validate_generation(packet)
    encoded, _expected, _bounds = observe_generation(packet["tokens"])
    if not isinstance(raw, str) or not raw or raw != encoded.translate(_DIGITS):
        raise ValueError("DECIMER raw SMILES differs from its retained tokens")
    return complete


def validate_generated_raw(packet, raw):
    """Bind the unmodified SDK-decoded observation to its complete token stream."""
    if not validate_generation_observation(packet, raw):
        raise ValueError("DECIMER generated-token completion is unproved")


def completed_observation(record):
    try:
        validate_generated_raw(record.get("generation"), record.get("raw_smiles"))
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def truncated_observation(record):
    """Only a literal, protocol-valid missing-end observation may be retried."""
    try:
        packet = record.get("generation")
        return (
            record.get("status") == "failed"
            and not validate_generation_observation(packet, record.get("raw_smiles"))
            and packet["reason"] == "missing_end"
        )
    except (AttributeError, TypeError, ValueError):
        return False


def generation_record_current(record):
    """Format currentness only, never chemical quality or successful completion."""
    try:
        if record.get("OCSR_engine") == "decimer":
            validate_generation_observation(
                record.get("generation"), record.get("raw_smiles")
            )
        elif record.get("OCSR_engine") == "molscribe":
            proof = record.get("stereo_rescue_proof") or {}
            validate_generated_raw(
                proof.get("primary_generation"), proof.get("primary_raw_smiles")
            )
        else:
            return False
        return True
    except (AttributeError, TypeError, ValueError):
        return False
