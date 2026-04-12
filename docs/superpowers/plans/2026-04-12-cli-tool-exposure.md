# CLI Tool Exposure & ToolPresentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose squackit's tools as `squackit tool <name>` CLI commands with dynamic discovery from fledgling's ToolInfo, and refactor scattered per-tool dicts into ToolPresentation.

**Architecture:** ToolPresentation wraps fledgling's ToolInfo via composition, adding squackit-specific presentation config (format, truncation, caching). A single `_OVERRIDES` dict replaces 8+ scattered dicts. One registry feeds both MCP server and CLI. The CLI uses a custom click.Group for multi-format name resolution (underscore, kebab, CamelCase).

**Tech Stack:** Python 3.12, click, fledgling (ToolInfo from v0.8.2), pluckit, pytest, Click's CliRunner for testing

**Environment:**
- Venv: `/home/teague/.local/share/venv/bin/python`
- Test: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v`
- squackit root: `/mnt/aux-data/teague/Projects/squackit`

---

## File Structure

| File | Responsibility |
|---|---|
| `squackit/tool_config.py` | **New** — ToolPresentation dataclass, _OVERRIDES, _SKIP, name normalization, registry builder |
| `squackit/cli.py` | **Modify** — Add --json flag, tool/t group with ToolGroup, tool list, dynamic command gen |
| `squackit/server.py` | **Modify** — Replace scattered dicts with ToolPresentation registry for MCP registration |
| `squackit/formatting.py` | **Modify** — Add format_json() for JSON output, keep existing markdown/text formatters |
| `tests/test_tool_config.py` | **New** — ToolPresentation, name normalization, registry builder tests |
| `tests/test_cli_tools.py` | **New** — CLI tool group integration tests via CliRunner |

---

### Task 1: ToolPresentation dataclass and name normalization

**Files:**
- Create: `squackit/tool_config.py`
- Create: `tests/test_tool_config.py`

- [ ] **Step 1: Write tests for name normalization**

```python
# tests/test_tool_config.py
"""Tests for squackit.tool_config — ToolPresentation and name resolution."""

from squackit.tool_config import normalize_tool_name, to_kebab, to_camel


class TestNameNormalization:
    """All three naming conventions resolve to underscore canonical form."""

    def test_underscore_passthrough(self):
        assert normalize_tool_name("find_definitions") == "find_definitions"

    def test_kebab_to_underscore(self):
        assert normalize_tool_name("find-definitions") == "find_definitions"

    def test_camel_to_underscore(self):
        assert normalize_tool_name("FindDefinitions") == "find_definitions"

    def test_single_word(self):
        assert normalize_tool_name("help") == "help"

    def test_camel_single_word(self):
        assert normalize_tool_name("Help") == "help"

    def test_consecutive_caps(self):
        # "AST" stays grouped: ASTSelect -> ast_select
        assert normalize_tool_name("ASTSelect") == "ast_select"


class TestToKebab:

    def test_simple(self):
        assert to_kebab("find_definitions") == "find-definitions"

    def test_single_word(self):
        assert to_kebab("help") == "help"


class TestToCamel:

    def test_simple(self):
        assert to_camel("find_definitions") == "FindDefinitions"

    def test_single_word(self):
        assert to_camel("help") == "Help"

    def test_three_parts(self):
        assert to_camel("read_doc_section") == "ReadDocSection"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tool_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'squackit.tool_config'`

- [ ] **Step 3: Implement name normalization functions**

```python
# squackit/tool_config.py
"""Tool configuration — ToolPresentation, name normalization, registry builder."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from fledgling.tools import ToolInfo


# ── Name normalization ────────────────────────────────────────────────
# Resolve CamelCase, kebab-case, and underscore to canonical underscore.

_CAMEL_RE = re.compile(r"([A-Z]+)([A-Z][a-z])|([a-z0-9])([A-Z])")


def normalize_tool_name(name: str) -> str:
    """Normalize any casing convention to underscore_case."""
    if "-" in name:
        return name.replace("-", "_")
    # CamelCase -> underscore
    s = _CAMEL_RE.sub(r"\1\3_\2\4", name)
    return s.lower()


def to_kebab(name: str) -> str:
    """Convert underscore_case to kebab-case."""
    return name.replace("_", "-")


def to_camel(name: str) -> str:
    """Convert underscore_case to CamelCase."""
    return "".join(part.capitalize() for part in name.split("_"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tool_config.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add squackit/tool_config.py tests/test_tool_config.py
git commit -m "feat: add name normalization (underscore/kebab/CamelCase)"
```

---

### Task 2: ToolPresentation dataclass

**Files:**
- Modify: `squackit/tool_config.py`
- Modify: `tests/test_tool_config.py`

- [ ] **Step 1: Write tests for ToolPresentation**

Append to `tests/test_tool_config.py`:

```python
from fledgling.tools import ToolInfo
from squackit.tool_config import ToolPresentation


class TestToolPresentation:
    """ToolPresentation wraps ToolInfo with squackit presentation config."""

    def _make_info(self, **kwargs) -> ToolInfo:
        defaults = dict(macro_name="read_source", params=["file_path", "lines", "ctx", "match"])
        defaults.update(kwargs)
        return ToolInfo(**defaults)

    def test_name_delegates_to_macro_name(self):
        tp = ToolPresentation(info=self._make_info())
        assert tp.name == "read_source"

    def test_name_prefers_tool_name(self):
        tp = ToolPresentation(info=self._make_info(tool_name="ReadLines"))
        assert tp.name == "ReadLines"

    def test_name_prefers_alias_over_tool_name(self):
        tp = ToolPresentation(
            info=self._make_info(tool_name="ReadLines"),
            alias="read_source",
        )
        assert tp.name == "read_source"

    def test_required_from_info_required(self):
        tp = ToolPresentation(info=self._make_info(required=["file_path"]))
        assert tp.required == ["file_path"]
        assert tp.optional == ["lines", "ctx", "match"]

    def test_required_fallback_to_required_params(self):
        """Catalog fallback: required_params returns all params."""
        tp = ToolPresentation(info=self._make_info())
        assert tp.required == ["file_path", "lines", "ctx", "match"]

    def test_required_override(self):
        tp = ToolPresentation(
            info=self._make_info(),
            required_override=["file_path"],
        )
        assert tp.required == ["file_path"]
        assert tp.optional == ["lines", "ctx", "match"]

    def test_format_from_info(self):
        tp = ToolPresentation(info=self._make_info(format="text"))
        assert tp.format == "text"

    def test_format_default_table(self):
        tp = ToolPresentation(info=self._make_info())
        assert tp.format == "table"

    def test_format_override(self):
        tp = ToolPresentation(
            info=self._make_info(format="markdown"),
            format_override="text",
        )
        assert tp.format == "text"

    def test_description_from_info(self):
        tp = ToolPresentation(info=self._make_info(description="Read file lines."))
        assert tp.description == "Read file lines."

    def test_description_fallback(self):
        tp = ToolPresentation(info=self._make_info())
        assert "read_source" in tp.description

    def test_description_override(self):
        tp = ToolPresentation(
            info=self._make_info(description="Original."),
            description_override="Custom.",
        )
        assert tp.description == "Custom."

    def test_parameters_schema_delegates(self):
        schema = {"file_path": {"type": "string"}}
        tp = ToolPresentation(info=self._make_info(parameters_schema=schema))
        assert tp.parameters_schema == schema

    def test_numeric_params_from_schema(self):
        schema = {
            "file_path": {"type": "string"},
            "ctx": {"type": "integer"},
            "n": {"type": "integer"},
        }
        tp = ToolPresentation(info=self._make_info(
            params=["file_path", "ctx", "n"],
            parameters_schema=schema,
        ))
        assert tp.numeric_params == {"ctx", "n"}

    def test_numeric_params_without_schema(self):
        tp = ToolPresentation(info=self._make_info())
        # Falls back to _FALLBACK_NUMERIC
        assert "ctx" in tp.numeric_params
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tool_config.py::TestToolPresentation -v`
Expected: FAIL — `ImportError: cannot import name 'ToolPresentation'`

- [ ] **Step 3: Implement ToolPresentation**

Add to `squackit/tool_config.py` after the name normalization functions:

```python
# ── Fallback numeric params ───────────────────────────────────────────
# Used when ToolInfo.parameters_schema is not available (catalog fallback).
_FALLBACK_NUMERIC = {
    "n", "max_lvl", "ctx", "center_line", "lim", "start_line", "end_line",
    "context_lines", "limit",
}


@dataclass
class ToolPresentation:
    """Wraps fledgling ToolInfo with squackit's presentation/UX config.

    Properties delegate to ToolInfo fields, with optional overrides for
    cases where squackit needs to customize behavior.
    """

    info: ToolInfo

    # Overrides (None = delegate to info)
    alias: str | None = None
    description_override: str | None = None
    format_override: Literal["table", "text"] | None = None
    required_override: list[str] | None = None

    # Squackit-specific presentation config
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tool_config.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add squackit/tool_config.py tests/test_tool_config.py
git commit -m "feat: add ToolPresentation dataclass wrapping fledgling ToolInfo"
```

---

### Task 3: Registry builder and _OVERRIDES

**Files:**
- Modify: `squackit/tool_config.py`
- Modify: `tests/test_tool_config.py`

- [ ] **Step 1: Write tests for the registry builder**

Append to `tests/test_tool_config.py`:

```python
from squackit.tool_config import build_tool_registry, SKIP, OVERRIDES


class TestBuildToolRegistry:
    """Registry builder discovers tools from fledgling and applies overrides."""

    def test_builds_from_tools_iterable(self):
        tools = [
            ToolInfo(macro_name="find_definitions", params=["file_pattern", "name_pattern"]),
            ToolInfo(macro_name="list_files", params=["pattern", "commit"]),
        ]
        registry = build_tool_registry(tools)
        assert "find_definitions" in registry
        assert "list_files" in registry
        assert len(registry) == 2

    def test_skips_macros_in_skip_set(self):
        tools = [
            ToolInfo(macro_name="find_definitions", params=["file_pattern"]),
            ToolInfo(macro_name="ast_ancestors", params=["ast_table", "child_node_id"]),
        ]
        registry = build_tool_registry(tools)
        assert "find_definitions" in registry
        assert "ast_ancestors" not in registry

    def test_applies_overrides(self):
        tools = [
            ToolInfo(macro_name="pss_render", params=["source", "selector"]),
        ]
        registry = build_tool_registry(tools)
        # pss_render should be aliased to select_code
        assert "select_code" in registry
        assert "pss_render" not in registry
        assert registry["select_code"].macro_name == "pss_render"

    def test_override_format(self):
        tools = [
            ToolInfo(macro_name="read_source", params=["file_path", "lines", "ctx", "match"]),
        ]
        registry = build_tool_registry(tools)
        assert registry["read_source"].format == "text"

    def test_override_required(self):
        tools = [
            ToolInfo(macro_name="read_source", params=["file_path", "lines", "ctx", "match"]),
        ]
        registry = build_tool_registry(tools)
        assert registry["read_source"].required == ["file_path"]

    def test_skip_set_covers_known_internal_macros(self):
        assert "ast_ancestors" in SKIP
        assert "load_conversations" in SKIP
        assert "ast_select" in SKIP

    def test_overrides_has_key_tools(self):
        assert "pss_render" in OVERRIDES
        assert "read_source" in OVERRIDES
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tool_config.py::TestBuildToolRegistry -v`
Expected: FAIL — `ImportError: cannot import name 'build_tool_registry'`

- [ ] **Step 3: Implement registry builder and OVERRIDES**

Add to `squackit/tool_config.py`:

```python
# ── Skip set ──────────────────────────────────────────────────────────
# Macros excluded from both MCP and CLI. Internal, too low-level, or
# superseded by better tools.

SKIP: set[str] = {
    # sitting_duck ast_* macros (take table references, not file paths)
    "ast_ancestors", "ast_call_arguments", "ast_children", "ast_class_members",
    "ast_containing_line", "ast_dead_code", "ast_definitions", "ast_descendants",
    "ast_function_metrics", "ast_function_scope", "ast_functions_containing",
    "ast_in_range", "ast_match", "ast_nesting_analysis", "ast_pattern",
    "ast_security_audit", "ast_siblings", "ast_definition_parent",
    # Other extension macros
    "duckdb_logs_parsed", "duckdb_profiling_settings",
    "histogram", "histogram_values",
    # Fledgling internal/low-level
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
# Transitional: will shrink as fledgling metadata improves.
# Keys are macro_name (not alias).

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
    "select_code": {
        "description_override": "Select code using CSS-like selectors over ASTs.",
        "format_override": "text",
        "range_params": frozenset({"selector"}),
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
    """Build the tool registry from an iterable of ToolInfo objects.

    Args:
        tools_iterable: Iterable of ToolInfo (e.g. con._tools).
        skip: Macro names to exclude. Defaults to SKIP.

    Returns:
        Dict keyed by presentation name (after aliasing).
    """
    skip = skip if skip is not None else SKIP
    registry: dict[str, ToolPresentation] = {}
    for tool_info in tools_iterable:
        if tool_info.macro_name in skip:
            continue
        overrides = OVERRIDES.get(tool_info.macro_name, {})
        presentation = ToolPresentation(info=tool_info, **overrides)
        registry[presentation.name] = presentation
    return registry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tool_config.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add squackit/tool_config.py tests/test_tool_config.py
git commit -m "feat: add tool registry builder with SKIP set and OVERRIDES"
```

---

### Task 4: JSON output formatter

**Files:**
- Modify: `squackit/formatting.py`

- [ ] **Step 1: Write test for JSON formatting**

Create `tests/test_formatting_json.py`:

```python
"""Tests for JSON output formatting."""

import json
from squackit.formatting import format_json


class TestFormatJson:

    def test_basic_table(self):
        cols = ["name", "kind", "start_line"]
        rows = [("main", "function", 10), ("Foo", "class", 25)]
        output = format_json(cols, rows)
        parsed = json.loads(output)
        assert len(parsed) == 2
        assert parsed[0] == {"name": "main", "kind": "function", "start_line": 10}
        assert parsed[1] == {"name": "Foo", "kind": "class", "start_line": 25}

    def test_empty_rows(self):
        cols = ["name"]
        rows = []
        output = format_json(cols, rows)
        assert json.loads(output) == []

    def test_none_values(self):
        cols = ["name", "value"]
        rows = [("test", None)]
        output = format_json(cols, rows)
        parsed = json.loads(output)
        assert parsed[0] == {"name": "test", "value": None}

    def test_single_column_text(self):
        cols = ["content"]
        rows = [("line 1",), ("line 2",)]
        output = format_json(cols, rows)
        parsed = json.loads(output)
        assert parsed == [{"content": "line 1"}, {"content": "line 2"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_formatting_json.py -v`
Expected: FAIL — `ImportError: cannot import name 'format_json'`

- [ ] **Step 3: Implement format_json**

Add to the end of `squackit/formatting.py`:

```python
import json as _json


def format_json(cols: list[str], rows: list[tuple]) -> str:
    """Format query results as a JSON array of objects."""
    result = [dict(zip(cols, row)) for row in rows]
    return _json.dumps(result, indent=2, default=str)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_formatting_json.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add squackit/formatting.py tests/test_formatting_json.py
git commit -m "feat: add JSON output formatter for CLI"
```

---

### Task 5: CLI tool group with ToolGroup and `tool list`

**Files:**
- Modify: `squackit/cli.py`
- Create: `tests/test_cli_tools.py`

- [ ] **Step 1: Write tests for CLI tool group**

```python
# tests/test_cli_tools.py
"""Tests for squackit CLI tool subcommands."""

import json
from click.testing import CliRunner
from squackit.cli import cli


runner = CliRunner()


class TestToolList:

    def test_tool_list_shows_tools(self):
        result = runner.invoke(cli, ["tool", "list"])
        assert result.exit_code == 0
        assert "find_definitions" in result.output

    def test_tool_list_json(self):
        result = runner.invoke(cli, ["--json", "tool", "list"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        names = [t["name"] for t in parsed]
        assert "find_definitions" in names

    def test_tool_alias_t(self):
        result = runner.invoke(cli, ["t", "list"])
        assert result.exit_code == 0
        assert "find_definitions" in result.output


class TestToolNameResolution:

    def test_underscore(self):
        result = runner.invoke(cli, ["tool", "find_definitions", "--help"])
        assert result.exit_code == 0
        assert "find_definitions" in result.output or "Find" in result.output

    def test_kebab(self):
        result = runner.invoke(cli, ["tool", "find-definitions", "--help"])
        assert result.exit_code == 0

    def test_camel(self):
        result = runner.invoke(cli, ["tool", "FindDefinitions", "--help"])
        assert result.exit_code == 0

    def test_unknown_tool(self):
        result = runner.invoke(cli, ["tool", "nonexistent_tool"])
        assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_cli_tools.py -v`
Expected: FAIL — no `tool` subcommand

- [ ] **Step 3: Implement CLI tool group**

Replace `squackit/cli.py` with:

```python
"""squackit CLI — entry point for the squackit MCP server."""

from __future__ import annotations

import json as _json

import click

from squackit.tool_config import (
    ToolPresentation,
    build_tool_registry,
    normalize_tool_name,
    to_kebab,
    to_camel,
)


# ── Global --json flag ────────────────────────────────────────────────

class JsonContext:
    def __init__(self, json_output=False):
        self.json_output = json_output


@click.group()
@click.version_option(package_name="squackit")
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Output in JSON format.")
@click.pass_context
def cli(ctx, json_output):
    """Semi-QUalified Agent Companion Kit — MCP server for fledgling-equipped agents."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output


# ── MCP serve ─────────────────────────────────────────────────────────

@cli.group()
def mcp():
    """MCP server commands."""


@mcp.command()
@click.option("--transport", "-t",
              type=click.Choice(["stdio", "sse"], case_sensitive=False),
              default="stdio", show_default=True, help="Transport protocol.")
@click.option("--port", "-p", type=int, default=8080, show_default=True,
              help="Port for SSE transport.")
@click.option("--root", type=click.Path(exists=True, file_okay=False),
              default=None, help="Project root directory (defaults to CWD).")
@click.option("--profile", default="analyst", show_default=True,
              help="Security profile.")
@click.option("--modules", "-m", multiple=True,
              help="SQL modules to load (repeatable).")
@click.option("--init", "init_path", default=None,
              help="Init file path. Pass 'false' to use sources only.")
def serve(transport, port, root, profile, modules, init_path):
    """Start the squackit MCP server."""
    from squackit.server import create_server

    init = None
    if init_path is not None:
        init = False if init_path.lower() == "false" else init_path

    server = create_server(
        root=root,
        init=init,
        modules=list(modules) or None,
        profile=profile,
    )

    kwargs = {}
    if transport == "sse":
        kwargs["transport"] = "sse"
        kwargs["port"] = port

    server.run(**kwargs)


# ── Tool group ────────────────────────────────────────────────────────

class ToolGroup(click.Group):
    """Click group that resolves tool names across naming conventions."""

    def get_command(self, ctx, cmd_name):
        # Try exact match first
        cmd = super().get_command(ctx, cmd_name)
        if cmd:
            return cmd
        # Normalize and retry
        normalized = normalize_tool_name(cmd_name)
        return super().get_command(ctx, normalized)

    def list_commands(self, ctx):
        base = super().list_commands(ctx)
        expanded = set()
        for name in base:
            expanded.add(name)
            expanded.add(to_kebab(name))
            expanded.add(to_camel(name))
        return sorted(expanded)


def _get_registry():
    """Lazily build the tool registry."""
    from pluckit import Plucker
    p = Plucker()
    con = p.connection
    return build_tool_registry(con._tools), con


def _make_tool_command(presentation: ToolPresentation, con) -> click.Command:
    """Generate a Click command from a ToolPresentation."""
    from squackit.formatting import _format_markdown_table, format_json

    params = []

    # Required params are positional arguments
    for p in presentation.required:
        params.append(click.Argument([p], required=True))

    # Optional params are --flags
    for p in presentation.optional:
        params.append(click.Option([f"--{p}"], default=None))

    @click.pass_context
    def callback(ctx, **kwargs):
        # Remove None values
        filtered = {k: v for k, v in kwargs.items() if v is not None}

        # Coerce numeric params
        for k in list(filtered):
            if k in presentation.numeric_params:
                try:
                    filtered[k] = int(filtered[k])
                except (TypeError, ValueError):
                    pass

        # Call the macro
        macro = getattr(con, presentation.macro_name)
        try:
            rel = macro(**filtered)
            cols = rel.columns
            rows = rel.fetchall()
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            ctx.exit(1)
            return

        if not rows:
            click.echo("(no results)")
            return

        # Format output
        json_output = ctx.obj.get("json", False) if ctx.obj else False
        if json_output:
            click.echo(format_json(cols, rows))
        elif presentation.format == "text":
            if len(cols) == 1:
                for row in rows:
                    click.echo(str(row[0]))
            elif "line_number" in cols and "content" in cols:
                ln_idx = cols.index("line_number")
                ct_idx = cols.index("content")
                for row in rows:
                    click.echo(f"{row[ln_idx]:4d}  {row[ct_idx]}")
            else:
                for row in rows:
                    parts = [str(v) for v in row if v is not None]
                    click.echo("  ".join(parts))
        else:
            click.echo(_format_markdown_table(cols, rows))

    return click.Command(
        name=presentation.name,
        help=presentation.description,
        params=params,
        callback=callback,
    )


class LazyToolGroup(ToolGroup):
    """ToolGroup that lazily loads tools on first access."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loaded = False
        self._con = None

    def _ensure_loaded(self, ctx):
        if self._loaded:
            return
        self._loaded = True
        try:
            registry, self._con = _get_registry()
        except Exception as e:
            click.echo(f"Warning: Could not load tools: {e}", err=True)
            return
        for name, presentation in registry.items():
            cmd = _make_tool_command(presentation, self._con)
            self.add_command(cmd, name)

    def get_command(self, ctx, cmd_name):
        self._ensure_loaded(ctx)
        return super().get_command(ctx, cmd_name)

    def list_commands(self, ctx):
        self._ensure_loaded(ctx)
        return super().list_commands(ctx)


@cli.group("tool", cls=LazyToolGroup)
@click.pass_context
def tool_group(ctx):
    """Run fledgling tools from the command line."""
    ctx.ensure_object(dict)


# Alias: squackit t
cli.add_command(tool_group, "t")


@tool_group.command("list")
@click.pass_context
def tool_list(ctx):
    """List available tools."""
    from squackit.formatting import _format_markdown_table, format_json

    tool_group_cmd = ctx.parent.command
    tool_group_cmd._ensure_loaded(ctx)

    # Collect tool info from registered commands
    tools = []
    seen = set()
    for name in sorted(tool_group_cmd.commands):
        if name == "list":
            continue
        # Skip kebab and CamelCase aliases
        normalized = normalize_tool_name(name)
        if normalized in seen:
            continue
        seen.add(normalized)

        cmd = tool_group_cmd.commands[name]
        tools.append({
            "name": normalized,
            "description": cmd.help or "",
        })

    json_output = ctx.obj.get("json", False) if ctx.obj else False
    if json_output:
        click.echo(_json.dumps(tools, indent=2))
    else:
        cols = ["Name", "Description"]
        rows = [(t["name"], t["description"][:60]) for t in tools]
        click.echo(_format_markdown_table(cols, rows))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_cli_tools.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v`
Expected: All tests PASS (184+ existing + new)

- [ ] **Step 6: Commit**

```bash
git add squackit/cli.py tests/test_cli_tools.py
git commit -m "feat: add 'squackit tool' CLI group with dynamic tool discovery"
```

---

### Task 6: Refactor server.py to use ToolPresentation registry

**Files:**
- Modify: `squackit/server.py`

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v`
Expected: All tests PASS (this is our safety net)

- [ ] **Step 2: Refactor server.py to use build_tool_registry**

Replace the tool registration section in `server.py`. The key change: replace all the scattered dicts with `build_tool_registry()`, and have `_register_tool` accept `ToolPresentation` instead of individual arguments. Keep the same behavior — this is a refactor, not a feature change.

Replace `squackit/server.py` with:

```python
"""squackit: FastMCP server wrapping fledgling's SQL macros.

Auto-generates MCP tools from every fledgling table macro. Each tool
accepts the macro's parameters and returns results as formatted text.

Usage::

    # As a module
    python -m squackit.server

    # Programmatic
    from squackit.server import create_server
    mcp = create_server()
    mcp.run()

    # With custom config
    mcp = create_server(root="/path/to/project", modules=["source", "code"])
    mcp.run()
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Optional

from pluckit import Plucker
from squackit.defaults import (
    ProjectDefaults, apply_defaults, infer_defaults, load_config,
)
import time as _time

from squackit.formatting import (
    _format_markdown_table,
    _truncate_rows,
    _HEAD_TAIL,
    _HINTS,
)
from squackit.prompts import register_prompts
from squackit.session import AccessLog, SessionCache
from squackit.tool_config import ToolPresentation, build_tool_registry
from squackit.workflows import register_workflows


def create_server(
    name: str = "squackit",
    root: Optional[str] = None,
    init: Optional[str | bool] = None,
    modules: Optional[list[str]] = None,
    profile: str = "analyst",
) -> FastMCP:
    """Create a FastMCP server with fledgling tools.

    Args:
        name: Server name.
        root: Project root. Defaults to CWD.
        init: Init file path, False for sources, None for auto-discover.
        modules: SQL modules to load (when using sources).
        profile: Security profile.

    Returns:
        A FastMCP server instance ready to .run().
    """
    from fastmcp import FastMCP

    con = Plucker(repo=root, profile=profile, modules=modules, init=init).connection
    mcp = FastMCP(name)

    # Infer smart defaults, merge with config file overrides
    project_root = Path(root) if root else Path.cwd()
    overrides = load_config(project_root)
    defaults = infer_defaults(con, overrides=overrides, root=project_root)
    mcp._defaults = defaults

    cache = SessionCache()
    access_log = AccessLog(con._con)
    mcp.session_cache = cache
    mcp.access_log = access_log

    # Build unified tool registry and register each as an MCP tool
    registry = build_tool_registry(con._tools)
    for presentation in registry.values():
        _register_tool(mcp, con, presentation, defaults, cache, access_log)

    # ── MCP Resources ───────────────────────────────────────────────
    # Static/slow-changing context available without tool calls.

    @mcp.resource("fledgling://project",
                  name="project",
                  description="Project overview — languages, file counts, directory structure.")
    def project_resource() -> str:
        sections = []

        overview = con.project_overview()
        sections.append("## Languages\n")
        sections.append(_format_markdown_table(overview.columns, overview.fetchall()))

        top_level = con.list_files("*")
        sections.append("\n## Top-Level Files\n")
        sections.append(_format_markdown_table(top_level.columns, top_level.fetchall()))

        return "\n".join(sections)

    @mcp.resource("fledgling://diagnostics",
                  name="diagnostics",
                  description="Fledgling version, profile, loaded modules, extensions.")
    def diagnostics_resource() -> str:
        diag = con.dr_fledgling()
        return _format_markdown_table(diag.columns, diag.fetchall())

    @mcp.resource("fledgling://docs",
                  name="docs",
                  description="Documentation outline — all markdown files with section headings.")
    def docs_resource() -> str:
        outline = con.doc_outline("**/*.md")
        return _format_markdown_table(outline.columns, outline.fetchall())

    @mcp.resource("fledgling://git",
                  name="git",
                  description="Current branch, recent commits, and working tree status.")
    def git_resource() -> str:
        sections = []

        branches = con.branch_list()
        sections.append("## Branches\n")
        sections.append(_format_markdown_table(branches.columns, branches.fetchall()))

        commits = con.recent_changes(5)
        sections.append("\n## Recent Commits\n")
        sections.append(_format_markdown_table(commits.columns, commits.fetchall()))

        status = con.working_tree_status()
        status_cols = status.columns
        status_rows = status.fetchall()
        sections.append("\n## Working Tree Status\n")
        if status_rows:
            sections.append(_format_markdown_table(status_cols, status_rows))
        else:
            sections.append("Clean working tree.")

        return "\n".join(sections)

    @mcp.resource("fledgling://session",
                  name="session",
                  description="Session access log — tool call history, cache stats.")
    def session_resource() -> str:
        summary = access_log.summary()
        total = summary["total_calls"]
        cached = summary["cached_calls"]
        pct = int(100 * cached / total) if total > 0 else 0
        entries = cache.entry_count()

        sections = []
        sections.append(
            f"Session: {total} tool calls, {cached} cached ({pct}%)\n"
            f"Cache: {entries} entries"
        )

        # Recent calls table
        recent = access_log.recent_calls(20)

        if recent:
            sections.append("\n## Recent Calls\n")
            cols = ["#", "tool", "args", "rows", "cached", "ms"]
            rows = []
            for r in recent:
                args_str = str(r[2])
                if len(args_str) > 60:
                    args_str = args_str[:57] + "..."
                rows.append((
                    r[0], r[1], args_str, r[3],
                    "yes" if r[4] else "no",
                    f"{r[5]:.0f}",
                ))
            sections.append(_format_markdown_table(cols, rows))

        return "\n".join(sections)

    # Register compound workflow tools
    register_workflows(mcp, con, defaults)

    # Register MCP prompt templates
    register_prompts(mcp, con, defaults)

    return mcp


def _register_tool(
    mcp,
    con,
    presentation: ToolPresentation,
    defaults: ProjectDefaults,
    cache: SessionCache,
    access_log: AccessLog,
):
    """Register a single tool as an MCP tool using ToolPresentation config."""
    tool_name = presentation.name
    macro_name = presentation.macro_name
    params = presentation.params
    description = presentation.description
    is_text = presentation.format == "text"
    numeric_params = presentation.numeric_params

    # Determine truncation config
    if presentation.max_lines is not None:
        limit_param = "max_lines"
        default_limit = presentation.max_lines
    elif presentation.max_rows is not None:
        limit_param = "max_results"
        default_limit = presentation.max_rows
    else:
        limit_param = None
        default_limit = 0

    range_params = presentation.range_params
    cache_ttl = presentation.cache_ttl
    cache_mtime_params = presentation.cache_mtime_params

    # Build the tool function dynamically
    async def tool_fn(**kwargs) -> str:
        t0 = _time.time()

        # Apply smart defaults for None params
        kwargs = apply_defaults(defaults, macro_name, kwargs)

        # Extract truncation parameter before passing to SQL macro
        max_rows = default_limit
        if limit_param and limit_param in kwargs:
            val = kwargs.pop(limit_param)
            if val is not None:
                try:
                    max_rows = int(val)
                except (TypeError, ValueError):
                    pass

        # Skip truncation if user provided a range-narrowing parameter
        if range_params and any(kwargs.get(p) is not None for p in range_params):
            max_rows = 0

        # Remove None values; coerce known numeric params to int.
        filtered = {}
        for k, v in kwargs.items():
            if v is None:
                continue
            if k in numeric_params and isinstance(v, str) and v.isdigit():
                filtered[k] = int(v)
            else:
                filtered[k] = v

        # Build cache args (include limit param since it affects output)
        cache_args = dict(filtered)
        if limit_param and max_rows != default_limit:
            cache_args[limit_param] = max_rows

        # Check cache
        if cache_ttl is not None:
            cached_entry = cache.get(tool_name, cache_args)
            if cached_entry is not None:
                elapsed = (_time.time() - t0) * 1000
                access_log.record(tool_name, cache_args, cached_entry.row_count,
                                  cached=True, elapsed_ms=elapsed)
                age = int(cached_entry.age_seconds())
                return f"(cached — same as {age}s ago)\n{cached_entry.text}"

        # Call macro
        macro = getattr(con, macro_name)
        try:
            rel = macro(**filtered)
            cols = rel.columns
            rows = rel.fetchall()
        except Exception as e:
            etype = type(e).__name__
            if etype in ("IOException", "InvalidInputException"):
                elapsed = (_time.time() - t0) * 1000
                access_log.record(tool_name, cache_args, 0,
                                  cached=False, elapsed_ms=elapsed)
                return "(no results)"
            raise
        if not rows:
            elapsed = (_time.time() - t0) * 1000
            access_log.record(tool_name, cache_args, 0,
                              cached=False, elapsed_ms=elapsed)
            return "(no results)"

        total_rows = len(rows)

        # Apply truncation
        omission = None
        if limit_param and max_rows > 0:
            rows, omission = _truncate_rows(rows, max_rows, macro_name)
        displayed_rows = len(rows)

        # Format output
        if is_text:
            if len(cols) == 1:
                lines = [str(r[0]) for r in rows]
            elif "line_number" in cols and "content" in cols:
                ln_idx = cols.index("line_number")
                ct_idx = cols.index("content")
                lines = [f"{r[ln_idx]:4d}  {r[ct_idx]}" for r in rows]
            else:
                lines = []
                for row in rows:
                    parts = [str(v) for v in row if v is not None]
                    lines.append("  ".join(parts))
            if omission:
                lines.insert(_HEAD_TAIL, omission)
            text = "\n".join(lines)
        else:
            text = _format_markdown_table(cols, rows)
            if omission:
                md_lines = text.split("\n")
                insert_at = 2 + _HEAD_TAIL
                md_lines.insert(insert_at, omission)
                text = "\n".join(md_lines)

        elapsed = (_time.time() - t0) * 1000

        # Store in cache
        if cache_ttl is not None:
            file_mtimes = {}
            for p in cache_mtime_params:
                path = filtered.get(p)
                if path:
                    try:
                        file_mtimes[path] = Path(path).stat().st_mtime
                    except OSError:
                        pass
            cache.put(tool_name, cache_args, text, displayed_rows,
                      ttl=cache_ttl, file_mtimes=file_mtimes)

        # Log access
        access_log.record(tool_name, cache_args, displayed_rows,
                          cached=False, elapsed_ms=elapsed)

        return text

    # Set function metadata for FastMCP
    tool_fn.__name__ = tool_name
    tool_fn.__qualname__ = tool_name
    tool_fn.__doc__ = description

    # Build parameter annotations for FastMCP schema generation
    # Use ToolInfo to determine required vs optional
    required_set = set(presentation.required)
    annotations = {}
    for p in params:
        if p in required_set:
            annotations[p] = str
        else:
            annotations[p] = Optional[str]
    if limit_param:
        annotations[limit_param] = Optional[int]
    tool_fn.__annotations__ = {**annotations, "return": str}

    # Create proper signature
    sig_params = []
    for p in params:
        if p in required_set:
            sig_params.append(inspect.Parameter(
                p,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str,
            ))
        else:
            sig_params.append(inspect.Parameter(
                p,
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=Optional[str],
            ))
    if limit_param:
        sig_params.append(inspect.Parameter(
            limit_param,
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=Optional[int],
        ))
    tool_fn.__signature__ = inspect.Signature(
        sig_params,
        return_annotation=str,
    )

    mcp.add_tool(tool_fn)


# ── Entry point ──────────────────────────────────────────────────────

def main():
    """Run the squackit MCP server."""
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run full test suite to verify no regressions**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v`
Expected: All tests PASS — same count as baseline. This is a behavior-preserving refactor.

- [ ] **Step 4: Commit**

```bash
git add squackit/server.py
git commit -m "refactor: replace scattered tool dicts with ToolPresentation registry"
```

---

### Task 7: Manual CLI smoke test and cleanup

**Files:**
- Modify: `squackit/formatting.py` (remove `_MAX_LINES`, `_MAX_ROWS` if no longer imported elsewhere)

- [ ] **Step 1: Check if formatting.py exports are still needed**

Run: `grep -r "_MAX_LINES\|_MAX_ROWS" squackit/ tests/ --include="*.py"`

If only `formatting.py` itself references them (used by `_truncate_rows`), they can stay. If `server.py` no longer imports them, remove the import from `server.py`.

The `_truncate_rows` function in `formatting.py` still uses `_MAX_LINES` to determine the unit ("lines" vs "rows") in the omission message. These dicts stay in `formatting.py` for now — `_truncate_rows` needs them.

- [ ] **Step 2: Reinstall the package**

Run: `/home/teague/.local/share/venv/bin/pip install -e /mnt/aux-data/teague/Projects/squackit`

- [ ] **Step 3: Manual smoke tests**

Run each command and verify output:

```bash
# Help
squackit --help
squackit tool --help
squackit t --help

# List tools
squackit tool list
squackit --json tool list

# Run a tool (table format)
squackit tool project_overview
squackit --json tool project_overview

# Run a tool (text format)
squackit tool read_source squackit/cli.py
squackit tool read-source squackit/cli.py --lines "1-10"
squackit tool ReadSource squackit/cli.py

# Name resolution
squackit tool find-definitions "**/*.py"
squackit tool FindDefinitions "**/*.py"
squackit t find_definitions "**/*.py"

# JSON output
squackit --json tool find_definitions "**/*.py"
```

- [ ] **Step 4: Run the full test suite one final time**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit any cleanup**

```bash
git add -A
git commit -m "chore: cleanup formatting imports after ToolPresentation refactor"
```

---

## Summary

| Task | What it builds | New tests |
|---|---|---|
| 1 | Name normalization (underscore/kebab/CamelCase) | 11 |
| 2 | ToolPresentation dataclass | ~15 |
| 3 | Registry builder, SKIP, OVERRIDES | ~7 |
| 4 | JSON output formatter | 4 |
| 5 | CLI tool group, LazyToolGroup, tool list | ~7 |
| 6 | server.py refactor to ToolPresentation | 0 (regression suite) |
| 7 | Smoke test and cleanup | 0 (manual) |
