"""Resolve prompt templates, falling back to hardcoded defaults.

An active DB prompt (tbl_LLM_Prompts) for a key takes precedence. When none
exists, the canonical hardcoded default (DEFAULT_PROMPTS) is used, so the
hardcoded prompt always remains the built-in fallback.

Rendering uses simple string replacement of {token} placeholders. This avoids
the .format() brace-escaping problem, since prompt schemas contain literal
JSON braces that must be left untouched.
"""

from __future__ import annotations

import logging

from app.db.queries import get_active_prompt
from app.utils.prompt_templates import DEFAULT_PROMPTS

logger = logging.getLogger(__name__)


def _render(template: str, **variables) -> str:
    if not variables:
        return template
    out = template
    for key, value in variables.items():
        out = out.replace("{" + key + "}", str(value))
    return out


async def resolve(key: str, **variables) -> str:
    """Return the rendered prompt for `key`, preferring an active DB version."""
    active: str | None = None
    try:
        active = await get_active_prompt(key)
    except Exception as e:
        logger.warning(f"Could not read active prompt for '{key}' ({e}); using hardcoded fallback.")

    if active:
        return _render(active, **variables)

    default = DEFAULT_PROMPTS.get(key)
    if default is None:
        raise KeyError(f"No prompt template defined for key '{key}'")
    return _render(default, **variables)