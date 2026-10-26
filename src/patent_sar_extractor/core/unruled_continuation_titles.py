"""Original literal continuation nominations, not row/compound assignments."""

from .caption_role_semantics import catalog_title_role, continuation_title
from .source_table_captions import table_caption_nominees
from .source_table_roles import observed_role, title_key
from .structure_column_scopes import original_column_context, original_column_title_args


def continuation_identity(text):
    return (
        (title_key(text), catalog_title_role(text))
        if continuation_title(text)
        else None
    )


def continuation_nominees(tokens, size, *, native_tokens=()):
    return [
        nomination
        for nomination in table_caption_nominees(
            tokens, size, native_tokens=native_tokens
        )
        if continuation_identity(nomination["text"])
    ]


def anchor_scope(scope):
    return scope.get("anchor_scope", scope)


def nominated_table_keys(scope):
    if anchor_scope(scope) is None:
        return set()
    return {
        title_key(p["text"])
        for p in original_column_context(anchor_scope(scope))
        if title_key(p["text"])
    }


def qualified_table_key(scope):
    if anchor_scope(scope) is None:
        return ""
    anchor = anchor_scope(scope)
    _role, key = observed_role(
        original_column_context(anchor), **original_column_title_args(anchor)
    )
    return key
