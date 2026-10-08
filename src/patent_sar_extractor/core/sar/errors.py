"""Fail-closed errors carry only developer-defined, nonraw machine codes."""


class SARInputError(ValueError):
    """An unsafe, unsupported or over-budget input, never an RDKit error body."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MappingLimit(ValueError):
    """Exhaustion means ambiguity, not absence of a chemical mapping."""
