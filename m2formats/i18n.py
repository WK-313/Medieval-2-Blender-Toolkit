"""English message formatting for the vendored format engine.

Message identifiers are retained in callers for straightforward upstream diffs.
The web catalogue and message registry are intentionally absent in Blender.
"""
import re

_FIELD = re.compile(r"\{([A-Za-z_]\w*)(?::([^{}]*))?\}")


def msg(mid: str, template: str, **params) -> str:
    """Format supplied fields, preserving unknown fields like the source engine."""
    def one(match):
        name, spec = match.group(1), match.group(2)
        if name not in params:
            return match.group(0)
        return format(params[name], spec or "")
    return _FIELD.sub(one, template)
