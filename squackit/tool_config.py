"""Tool configuration — ToolPresentation, name normalization, registry builder."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

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


# ── Fallback numeric params ───────────────────────────────────────────
_FALLBACK_NUMERIC = {
    "n", "max_lvl", "ctx", "center_line", "lim", "start_line", "end_line",
    "context_lines", "limit",
}


@dataclass
class ToolPresentation:
    """Wraps fledgling ToolInfo with squackit's presentation/UX config."""

    info: ToolInfo

    alias: str | None = None
    description_override: str | None = None
    format_override: Literal["table", "text"] | None = None
    required_override: list[str] | None = None

    max_rows: int | None = None
    max_lines: int | None = None
    range_params: frozenset[str] = field(default_factory=frozenset)
    cache_ttl: int | None = None
    cache_mtime_params: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        if self.alias is not None:
            return self.alias
        return self.info.tool_name or self.info.macro_name

    @property
    def macro_name(self) -> str:
        return self.info.macro_name

    @property
    def params(self) -> list[str]:
        return self.info.params

    @property
    def required(self) -> list[str]:
        if self.required_override is not None:
            return self.required_override
        if self.info.required is not None:
            req_set = set(self.info.required)
            return [p for p in self.params if p in req_set]
        return self.info.required_params

    @property
    def optional(self) -> list[str]:
        req = set(self.required)
        return [p for p in self.params if p not in req]

    @property
    def format(self) -> str:
        if self.format_override is not None:
            return self.format_override
        return self.info.format or "table"

    @property
    def description(self) -> str:
        if self.description_override is not None:
            return self.description_override
        return self.info.description or f"Query: {self.name}({', '.join(self.params)})"

    @property
    def parameters_schema(self) -> dict | None:
        return self.info.parameters_schema

    @property
    def numeric_params(self) -> set[str]:
        schema = self.info.parameters_schema
        if schema:
            return {
                name for name, props in schema.items()
                if props.get("type") in ("integer", "number")
            }
        return {p for p in self.params if p in _FALLBACK_NUMERIC}
