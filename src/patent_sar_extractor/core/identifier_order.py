"""Natural identifier order is presentation, never source identity inference."""

import re


def natural_identifier_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.casefold())
        for token in re.split(r"([0-9]+)", str(value))
    )
