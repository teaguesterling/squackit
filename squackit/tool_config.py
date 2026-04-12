"""Tool configuration — ToolPresentation, name normalization, registry builder."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from fledgling.tools import ToolInfo


_CAMEL_RE = re.compile(r"([A-Z]+)([A-Z][a-z])|([a-z0-9])([A-Z])")


def normalize_tool_name(name: str) -> str:
    """Normalize any casing convention to underscore_case."""
    if "-" in name:
        return name.replace("-", "_")
    s = _CAMEL_RE.sub(r"\1\3_\2\4", name)
    return s.lower()


def to_kebab(name: str) -> str:
    """Convert underscore_case to kebab-case."""
    return name.replace("_", "-")


def to_camel(name: str) -> str:
    """Convert underscore_case to CamelCase."""
    return "".join(part.capitalize() for part in name.split("_"))
