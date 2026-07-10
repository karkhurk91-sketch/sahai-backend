import re
from typing import Any, Dict, Mapping

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def _resolve_context_value(context: Mapping[str, Any] | None, key: str) -> Any:
    if not context:
        return None
    current: Any = context
    for part in key.split("."):
        if isinstance(current, Mapping):
            current = current.get(part)
        else:
            return None
    return current


def render_quick_reply_content(content: str | None, context: Mapping[str, Any] | None = None) -> str:
    if not content:
        return ""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = _resolve_context_value(context, key)
        if value is None:
            return ""
        return str(value)

    return _PLACEHOLDER_PATTERN.sub(replace, content)
