"""One original-document identity for call-local source observers."""

import hashlib
from pathlib import Path


def document_sha256(doc):
    if doc.name and not doc.is_dirty:
        with Path(doc.name).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    return hashlib.sha256(doc.tobytes(no_new_id=True)).hexdigest()
