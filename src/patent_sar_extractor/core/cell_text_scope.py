"""Bounded physical typography claims, subordinate to each trusted caller."""


def text_scope(maximum_rows, maximum_row_height):
    if (
        type(maximum_rows) is not int
        or not 2 <= maximum_rows <= 32
        or type(maximum_row_height) is not int
        or not 0 < maximum_row_height <= 128
    ):
        raise ValueError("Invalid original text typography scope")
    return {"maximum_rows": maximum_rows, "maximum_row_height": maximum_row_height}


def scoped_height(reading, *, maximum_row_height, maximum_rows=None):
    """Saved limits can narrow the caller's authority, never enlarge it."""
    if "text_scope" not in reading:
        return maximum_row_height
    scope = reading["text_scope"]
    if not isinstance(scope, dict) or set(scope) != {
        "maximum_rows",
        "maximum_row_height",
    }:
        raise ValueError("Malformed original text typography scope")
    text_scope(scope["maximum_rows"], scope["maximum_row_height"])
    if scope["maximum_row_height"] > maximum_row_height or (
        maximum_rows is not None and scope["maximum_rows"] != maximum_rows
    ):
        raise ValueError("Original text typography exceeds its caller's scope")
    return scope["maximum_row_height"]
