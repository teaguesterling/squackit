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


# ── Skip set ──────────────────────────────────────────────────────────

SKIP: set[str] = {
    "ast_ancestors", "ast_call_arguments", "ast_children", "ast_class_members",
    "ast_containing_line", "ast_dead_code", "ast_definitions", "ast_descendants",
    "ast_function_metrics", "ast_function_scope", "ast_functions_containing",
    "ast_in_range", "ast_match", "ast_nesting_analysis", "ast_pattern",
    "ast_security_audit", "ast_siblings", "ast_definition_parent",
    "duckdb_logs_parsed", "duckdb_profiling_settings",
    "histogram", "histogram_values",
    "load_conversations",
    "read_source_batch",
    "file_line_count",
    "content_blocks",
    "tool_results",
    "token_usage",
    "tool_frequency",
    "bash_commands",
    "session_summary",
    "model_usage",
    "search_tool_inputs",
    "find_in_ast",
    "find_calls",
    "find_imports",
    "ast_select",
    "ast_select_list",
    "ast_select_rules",
    "ast_select_render",
    "find_code_examples",
    "doc_stats",
    "repo_files",
    "module_dependencies",
    "function_callers",
}

# ── Per-tool overrides ────────────────────────────────────────────────

OVERRIDES: dict[str, dict] = {
    "pss_render": {
        "alias": "select_code",
        "description_override": "Select code using CSS-like selectors over ASTs.",
        "format_override": "text",
        "required_override": ["source"],
    },
    "read_source": {
        "description_override": "Read file lines with optional range, context, and match filtering.",
        "format_override": "text",
        "required_override": ["file_path"],
        "max_lines": 200,
        "range_params": frozenset({"lines", "match"}),
        "cache_ttl": 300,
        "cache_mtime_params": ("file_path",),
    },
    "read_context": {
        "description_override": "Read lines centered around a specific line number.",
        "format_override": "text",
        "required_override": ["file_path", "center_line"],
        "max_lines": 50,
        "cache_ttl": 300,
        "cache_mtime_params": ("file_path",),
    },
    "file_diff": {
        "description_override": "Line-level unified diff between revisions.",
        "format_override": "text",
        "required_override": ["file"],
        "max_lines": 300,
    },
    "file_at_version": {
        "description_override": "File content at a specific git revision.",
        "format_override": "text",
        "required_override": ["file", "rev"],
        "max_lines": 200,
    },
    "read_doc_section": {
        "format_override": "text",
        "required_override": ["file_path", "target_id"],
    },
    "help": {
        "format_override": "text",
    },
    "find_definitions": {
        "description_override": "Find function, class, and module definitions by AST analysis.",
        "required_override": ["file_pattern"],
        "max_rows": 50,
        "range_params": frozenset({"name_pattern"}),
        "cache_ttl": 300,
    },
    "code_structure": {
        "description_override": "Structural overview with complexity metrics.",
        "required_override": ["file_pattern"],
        "cache_ttl": 300,
    },
    "list_files": {
        "description_override": "Find files by glob pattern.",
        "required_override": ["pattern"],
        "max_rows": 100,
    },
    "doc_outline": {
        "description_override": "Markdown section outlines with optional keyword/regex search.",
        "required_override": ["file_pattern"],
        "max_rows": 50,
        "range_params": frozenset({"search"}),
        "cache_ttl": 0,
    },
    "project_overview": {
        "description_override": "File counts by language for the project.",
        "required_override": [],
        "cache_ttl": 0,
    },
    "recent_changes": {
        "description_override": "Git commit history.",
        "required_override": [],
        "max_rows": 20,
        "cache_ttl": 30,
    },
    "file_changes": {
        "description_override": "Files changed between two git revisions.",
        "required_override": ["from_rev", "to_rev"],
        "max_rows": 25,
    },
    "branch_list": {
        "description_override": "List git branches.",
        "required_override": [],
    },
    "tag_list": {
        "description_override": "List git tags.",
        "required_override": [],
    },
    "working_tree_status": {
        "description_override": "Untracked and modified files.",
        "required_override": [],
        "cache_ttl": 10,
    },
    "structural_diff": {
        "description_override": "Semantic diff: added/removed/modified definitions between revisions.",
        "required_override": ["file"],
    },
    "changed_function_summary": {
        "description_override": "Changed functions ranked by complexity between revisions.",
        "required_override": ["from_rev", "to_rev"],
    },
    "complexity_hotspots": {
        "description_override": "Most complex functions in the codebase.",
        "required_override": ["file_pattern"],
    },
}


def build_tool_registry(
    tools_iterable,
    skip: set[str] | None = None,
) -> dict[str, ToolPresentation]:
    """Build the tool registry from an iterable of ToolInfo objects."""
    skip = skip if skip is not None else SKIP
    registry: dict[str, ToolPresentation] = {}
    for tool_info in tools_iterable:
        if tool_info.macro_name in skip:
            continue
        overrides = OVERRIDES.get(tool_info.macro_name, {})
        presentation = ToolPresentation(info=tool_info, **overrides)
        registry[presentation.name] = presentation
    return registry
