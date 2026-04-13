# Pluckit Tool Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose pluckit's `view`, `find`, `find_names`, and `complexity` as first-class tools in squackit's CLI and MCP, masking redundant fledgling equivalents.

**Architecture:** ToolPresentation gains an `executor` field. Pluckit tool functions live in `squackit/tools.py`. The registry builder accepts `extra_tools` with priority over fledgling macros. CLI and MCP execution paths type-dispatch on executor return values (DuckDB relation, View, list).

**Tech Stack:** Python 3.12, pluckit (Selection, View, AstViewer), fledgling (ToolInfo), click, pytest

**Environment:**
- Venv: `/home/teague/.local/share/venv/bin/python`
- Test: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v`
- squackit root: `/mnt/aux-data/teague/Projects/squackit`

---

## File Structure

| File | Responsibility |
|---|---|
| `squackit/tool_config.py` | **Modify** -- add `executor` field, `extra_tools` param, `MASKED_BY_PLUCKIT` |
| `squackit/tools.py` | **New** -- pluckit tool executors, ToolInfo/ToolPresentation definitions, PLUCKIT_TOOLS |
| `squackit/cli.py` | **Modify** -- executor dispatch in callback, import PLUCKIT_TOOLS in `_get_registry` |
| `squackit/server.py` | **Modify** -- executor dispatch in `_register_tool`, import PLUCKIT_TOOLS in `create_server` |
| `tests/test_tools.py` | **New** -- pluckit executor unit tests |
| `tests/test_cli_tools.py` | **Modify** -- add pluckit tool CLI tests |

---

### Task 1: Add executor field and extra_tools to tool_config.py

**Files:**
- Modify: `squackit/tool_config.py`
- Modify: `tests/test_tool_config.py`

- [ ] **Step 1: Write tests for executor field and extra_tools**

Append to `tests/test_tool_config.py`:

```python
class TestExecutorField:

    def test_executor_default_none(self):
        info = ToolInfo(macro_name="test", params=["a"])
        tp = ToolPresentation(info=info)
        assert tp.executor is None

    def test_executor_set(self):
        def my_exec(**kwargs):
            return kwargs
        info = ToolInfo(macro_name="test", params=["a"])
        tp = ToolPresentation(info=info, executor=my_exec)
        assert tp.executor is my_exec


class TestExtraTools:

    def test_extra_tools_registered(self):
        def my_exec(**kwargs):
            return kwargs
        extra = [
            ToolPresentation(
                info=ToolInfo(macro_name="my_tool", params=["x"]),
                executor=my_exec,
            ),
        ]
        fledgling_tools = [
            ToolInfo(macro_name="list_files", params=["pattern"]),
        ]
        registry = build_tool_registry(fledgling_tools, extra_tools=extra)
        assert "my_tool" in registry
        assert "list_files" in registry

    def test_extra_tools_take_priority(self):
        def my_exec(**kwargs):
            return kwargs
        extra = [
            ToolPresentation(
                info=ToolInfo(macro_name="find_definitions", params=["source", "selector"]),
                executor=my_exec,
            ),
        ]
        fledgling_tools = [
            ToolInfo(macro_name="find_definitions", params=["file_pattern", "name_pattern"]),
        ]
        registry = build_tool_registry(fledgling_tools, extra_tools=extra)
        assert registry["find_definitions"].executor is my_exec

    def test_masked_by_pluckit(self):
        from squackit.tool_config import MASKED_BY_PLUCKIT
        assert "pss_render" in MASKED_BY_PLUCKIT
        assert "find_definitions" in MASKED_BY_PLUCKIT
        assert "code_structure" in MASKED_BY_PLUCKIT
        assert "complexity_hotspots" in MASKED_BY_PLUCKIT

    def test_masked_tools_skipped_when_extra_present(self):
        def my_exec(**kwargs):
            return kwargs
        extra = [
            ToolPresentation(
                info=ToolInfo(macro_name="view", params=["source", "selector"]),
                executor=my_exec,
            ),
        ]
        fledgling_tools = [
            ToolInfo(macro_name="pss_render", params=["source", "selector"]),
            ToolInfo(macro_name="list_files", params=["pattern"]),
        ]
        registry = build_tool_registry(fledgling_tools, extra_tools=extra)
        assert "view" in registry
        assert "select_code" not in registry
        assert "list_files" in registry
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tool_config.py::TestExecutorField tests/test_tool_config.py::TestExtraTools -v`
Expected: FAIL

- [ ] **Step 3: Implement changes to tool_config.py**

Add `Callable` to imports:

```python
from typing import Callable, Literal, Optional
```

Add `executor` field to ToolPresentation after `cache_mtime_params`:

```python
    executor: Callable | None = None
```

Add `MASKED_BY_PLUCKIT` set after the OVERRIDES dict:

```python
MASKED_BY_PLUCKIT: set[str] = {
    "pss_render",
    "find_definitions",
    "code_structure",
    "complexity_hotspots",
}
```

Update `build_tool_registry`:

```python
def build_tool_registry(
    tools_iterable,
    skip: set[str] | None = None,
    extra_tools: list[ToolPresentation] | None = None,
) -> dict[str, ToolPresentation]:
    """Build the tool registry from an iterable of ToolInfo objects."""
    skip = skip if skip is not None else SKIP
    registry: dict[str, ToolPresentation] = {}

    if extra_tools:
        skip = skip | MASKED_BY_PLUCKIT
        for tp in extra_tools:
            registry[tp.name] = tp

    for tool_info in tools_iterable:
        if tool_info.macro_name in skip:
            continue
        overrides = OVERRIDES.get(tool_info.macro_name, {})
        presentation = ToolPresentation(info=tool_info, **overrides)
        if presentation.name not in registry:
            registry[presentation.name] = presentation

    return registry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tool_config.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add squackit/tool_config.py tests/test_tool_config.py
git commit -m "feat: add executor field, extra_tools priority, and MASKED_BY_PLUCKIT"
```

---

### Task 2: Create pluckit tool executors in squackit/tools.py

**Files:**
- Create: `squackit/tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write tests for pluckit executors**

```python
# tests/test_tools.py
"""Tests for squackit.tools -- pluckit-backed tool executors."""

import pytest
from squackit.tools import (
    PLUCKIT_TOOLS,
    view_executor,
    find_executor,
    find_names_executor,
    complexity_executor,
)


class TestViewExecutor:

    def test_returns_view_object(self):
        from pluckit.plugins.viewer import View
        result = view_executor(source="squackit/**/*.py", selector=".fn")
        assert isinstance(result, View)

    def test_view_has_markdown(self):
        result = view_executor(source="squackit/cli.py", selector=".fn#cli")
        assert "def cli" in result.markdown

    def test_view_has_blocks(self):
        result = view_executor(source="squackit/**/*.py", selector=".fn")
        assert len(result.blocks) > 0


class TestFindExecutor:

    def test_returns_relation(self):
        result = find_executor(source="squackit/**/*.py", selector=".fn")
        assert hasattr(result, "columns")
        assert hasattr(result, "fetchall")

    def test_relation_has_expected_columns(self):
        result = find_executor(source="squackit/**/*.py", selector=".fn")
        assert "name" in result.columns
        assert "file_path" in result.columns
        assert "start_line" in result.columns

    def test_finds_known_function(self):
        result = find_executor(source="squackit/cli.py", selector=".fn#cli")
        rows = result.fetchall()
        assert len(rows) >= 1


class TestFindNamesExecutor:

    def test_returns_list_of_strings(self):
        result = find_names_executor(source="squackit/**/*.py", selector=".fn")
        assert isinstance(result, list)
        assert all(isinstance(n, str) for n in result)

    def test_finds_known_function(self):
        result = find_names_executor(source="squackit/cli.py", selector=".fn")
        assert "cli" in result


class TestComplexityExecutor:

    def test_returns_relation(self):
        result = complexity_executor(source="squackit/**/*.py", selector=".fn")
        assert hasattr(result, "columns")
        assert "complexity" in result.columns

    def test_ordered_by_complexity_desc(self):
        result = complexity_executor(source="squackit/**/*.py", selector=".fn")
        rows = result.fetchall()
        cx_idx = result.columns.index("complexity")
        complexities = [r[cx_idx] for r in rows]
        assert complexities == sorted(complexities, reverse=True)


class TestPluckitToolsList:

    def test_four_tools_defined(self):
        assert len(PLUCKIT_TOOLS) == 4

    def test_all_have_executors(self):
        for tp in PLUCKIT_TOOLS:
            assert tp.executor is not None

    def test_tool_names(self):
        names = {tp.name for tp in PLUCKIT_TOOLS}
        assert names == {"view", "find", "find_names", "complexity"}

    def test_all_require_source_and_selector(self):
        for tp in PLUCKIT_TOOLS:
            assert "source" in tp.required
            assert "selector" in tp.required
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement squackit/tools.py**

```python
# squackit/tools.py
"""Pluckit-backed tools for squackit's tool namespace.

These tools wrap pluckit's CSS selector API and are registered alongside
fledgling macro tools. They take priority over fledgling equivalents
(find_definitions, code_structure, complexity_hotspots, select_code).
"""

from __future__ import annotations

from fledgling.tools import ToolInfo
from squackit.tool_config import ToolPresentation


def _make_plucker():
    """Create a Plucker with AstViewer for tool execution."""
    from pluckit import Plucker
    from pluckit.plugins.viewer import AstViewer
    return Plucker(plugins=[AstViewer])


def view_executor(*, source: str, selector: str):
    """Execute a view query, returning rendered source code."""
    p = _make_plucker()
    return p.source(source).view(selector)


def find_executor(*, source: str, selector: str):
    """Execute a find query, returning matched AST nodes as a relation."""
    p = _make_plucker()
    return p.source(source).find(selector).relation


def find_names_executor(*, source: str, selector: str) -> list[str]:
    """Execute a find query, returning just the names."""
    p = _make_plucker()
    return p.source(source).find(selector).names()


def complexity_executor(*, source: str, selector: str):
    """Execute a find query with complexity metrics, ranked by complexity."""
    p = _make_plucker()
    sel = p.source(source).find(selector)
    view_name = sel._register("cx")
    try:
        rel = sel._ctx.db.sql(
            f"SELECT name, file_path, start_line, end_line, "
            f"descendant_count AS complexity, peek AS signature "
            f"FROM {view_name} ORDER BY descendant_count DESC"
        )
    except Exception:
        sel._unregister(view_name)
        raise
    return rel


# -- Tool definitions --

VIEW_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="view",
        params=["source", "selector"],
        description="View source code matching CSS selectors. Returns rendered "
                    "markdown with file headings and source blocks.",
        required=["source", "selector"],
    ),
    format_override="text",
    executor=view_executor,
)

FIND_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="find",
        params=["source", "selector"],
        description="Find AST nodes matching CSS selectors. Returns file paths, "
                    "names, line ranges.",
        required=["source", "selector"],
    ),
    executor=find_executor,
)

FIND_NAMES_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="find_names",
        params=["source", "selector"],
        description="Find names of AST nodes matching CSS selectors.",
        required=["source", "selector"],
    ),
    executor=find_names_executor,
)

COMPLEXITY_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="complexity",
        params=["source", "selector"],
        description="Find AST nodes matching CSS selectors, ranked by complexity.",
        required=["source", "selector"],
    ),
    executor=complexity_executor,
)

PLUCKIT_TOOLS = [VIEW_TOOL, FIND_TOOL, FIND_NAMES_TOOL, COMPLEXITY_TOOL]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_tools.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add squackit/tools.py tests/test_tools.py
git commit -m "feat: add pluckit tool executors (view, find, find_names, complexity)"
```

---

### Task 3: Wire executor dispatch into CLI

**Files:**
- Modify: `squackit/cli.py`
- Modify: `tests/test_cli_tools.py`

- [ ] **Step 1: Write tests for pluckit tools via CLI**

Append to `tests/test_cli_tools.py`:

```python
class TestPluckitToolsCli:

    def test_view_tool_exists(self):
        result = runner.invoke(cli, ["tool", "view", "--help"])
        assert result.exit_code == 0
        assert "selector" in result.output

    def test_find_tool_exists(self):
        result = runner.invoke(cli, ["tool", "find", "--help"])
        assert result.exit_code == 0
        assert "selector" in result.output

    def test_find_names_tool_exists(self):
        result = runner.invoke(cli, ["tool", "find_names", "--help"])
        assert result.exit_code == 0

    def test_complexity_tool_exists(self):
        result = runner.invoke(cli, ["tool", "complexity", "--help"])
        assert result.exit_code == 0

    def test_find_definitions_masked(self):
        """find_definitions should be masked when pluckit tools are present."""
        result = runner.invoke(cli, ["tool", "find_definitions", "--help"])
        assert result.exit_code != 0

    def test_view_runs(self):
        result = runner.invoke(cli, ["tool", "view", "squackit/cli.py", ".fn#cli"])
        assert result.exit_code == 0
        assert "def cli" in result.output

    def test_find_runs(self):
        result = runner.invoke(cli, ["tool", "find", "squackit/**/*.py", ".fn"])
        assert result.exit_code == 0

    def test_find_names_runs(self):
        result = runner.invoke(cli, ["tool", "find_names", "squackit/cli.py", ".fn"])
        assert result.exit_code == 0
        assert "cli" in result.output

    def test_find_json(self):
        result = runner.invoke(cli, ["--json", "tool", "find", "squackit/cli.py", ".fn"])
        assert result.exit_code == 0
        import json
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_cli_tools.py::TestPluckitToolsCli -v`
Expected: FAIL

- [ ] **Step 3: Update _get_registry to include pluckit tools**

In `squackit/cli.py`, change `_get_registry`:

```python
def _get_registry():
    """Lazily build the tool registry."""
    from pluckit import Plucker
    from squackit.tools import PLUCKIT_TOOLS
    p = Plucker()
    con = p.connection
    return build_tool_registry(con._tools, extra_tools=PLUCKIT_TOOLS), con
```

- [ ] **Step 4: Add _format_result helper and update _make_tool_command callback**

Add `_format_result` function before `_make_tool_command`:

```python
def _format_result(result, presentation, json_output):
    """Format and output a tool result based on its type."""
    from squackit.formatting import _format_markdown_table, format_json
    import json as _json

    # View object (pluckit)
    if hasattr(result, 'markdown') and hasattr(result, 'tabular'):
        if json_output:
            cols, rows = result.tabular
            click.echo(format_json(cols, rows))
        else:
            click.echo(result.markdown)
        return

    # list of strings (find_names)
    if isinstance(result, list) and result and isinstance(result[0], str):
        if json_output:
            click.echo(_json.dumps(result, indent=2))
        else:
            for item in result:
                click.echo(item)
        return

    # DuckDB relation (fledgling macros, pluckit find/complexity)
    if hasattr(result, 'columns') and hasattr(result, 'fetchall'):
        cols = result.columns
        rows = result.fetchall()
        if not rows:
            click.echo("(no results)")
            return
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
        return

    # Fallback: string or empty
    click.echo(str(result) if result else "(no results)")
```

Replace the callback in `_make_tool_command` with:

```python
    @click.pass_context
    def callback(click_ctx, **kwargs):
        filtered = {k: v for k, v in kwargs.items() if v is not None}

        for k in list(filtered):
            if k in presentation.numeric_params:
                try:
                    filtered[k] = int(filtered[k])
                except (TypeError, ValueError):
                    pass

        try:
            if presentation.executor:
                result = presentation.executor(**filtered)
            else:
                macro = getattr(con, presentation.macro_name)
                result = macro(**filtered)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            click_ctx.exit(1)
            return

        json_output = click_ctx.obj.get("json", False) if click_ctx.obj else False
        _format_result(result, presentation, json_output)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/test_cli_tools.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add squackit/cli.py tests/test_cli_tools.py
git commit -m "feat: wire pluckit tools into CLI with executor dispatch"
```

---

### Task 4: Wire executor dispatch into MCP server

**Files:**
- Modify: `squackit/server.py`

- [ ] **Step 1: Run existing test suite to establish baseline**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v 2>&1 | tail -5`

- [ ] **Step 2: Update create_server to include pluckit tools**

In `squackit/server.py`, change the registry building:

```python
    # Register each macro as an MCP tool
    from squackit.tools import PLUCKIT_TOOLS
    registry = build_tool_registry(con._tools, extra_tools=PLUCKIT_TOOLS)
    for presentation in registry.values():
        _register_tool(mcp, con, presentation, defaults, cache, access_log)
```

- [ ] **Step 3: Add _register_executor_tool and update _register_tool**

Add `_register_executor_tool` before `_register_tool`:

```python
def _register_executor_tool(mcp, presentation: ToolPresentation):
    """Register an executor-based tool (e.g. pluckit) as an MCP tool."""
    tool_name = presentation.name
    params = presentation.params
    description = presentation.description
    is_text = presentation.format == "text"
    executor = presentation.executor

    async def tool_fn(**kwargs) -> str:
        filtered = {k: v for k, v in kwargs.items() if v is not None}

        try:
            result = executor(**filtered)
        except Exception as e:
            etype = type(e).__name__
            if etype == "PluckerError":
                return f"Error: {e}"
            raise

        # View -> markdown
        if hasattr(result, 'markdown'):
            return result.markdown or "(no results)"
        # DuckDB relation -> table
        if hasattr(result, 'columns') and hasattr(result, 'fetchall'):
            cols = result.columns
            rows = result.fetchall()
            if not rows:
                return "(no results)"
            if is_text:
                lines = []
                for row in rows:
                    parts = [str(v) for v in row if v is not None]
                    lines.append("  ".join(parts))
                return "\n".join(lines)
            return _format_markdown_table(cols, rows)
        # list -> joined
        if isinstance(result, list):
            return "\n".join(str(item) for item in result) if result else "(no results)"
        return str(result) if result else "(no results)"

    tool_fn.__name__ = tool_name
    tool_fn.__qualname__ = tool_name
    tool_fn.__doc__ = description

    required_set = set(presentation.required)
    annotations = {}
    sig_params = []
    for p in params:
        if p in required_set:
            annotations[p] = str
            sig_params.append(inspect.Parameter(
                p, inspect.Parameter.KEYWORD_ONLY, annotation=str,
            ))
        else:
            annotations[p] = Optional[str]
            sig_params.append(inspect.Parameter(
                p, inspect.Parameter.KEYWORD_ONLY,
                default=None, annotation=Optional[str],
            ))
    tool_fn.__annotations__ = {**annotations, "return": str}
    tool_fn.__signature__ = inspect.Signature(
        sig_params, return_annotation=str,
    )

    mcp.add_tool(tool_fn)
```

Add early return at the top of `_register_tool`:

```python
def _register_tool(mcp, con, presentation, defaults, cache, access_log):
    """Register a single tool as an MCP tool using ToolPresentation config."""
    if presentation.executor:
        _register_executor_tool(mcp, presentation)
        return

    # ... existing macro-based registration continues unchanged ...
```

- [ ] **Step 4: Run full test suite**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v`
Expected: All tests PASS. If tests that checked for masked tool names (find_definitions, select_code) fail, update them.

- [ ] **Step 5: Commit**

```bash
git add squackit/server.py
git commit -m "feat: wire pluckit tools into MCP server with executor dispatch"
```

---

### Task 5: Smoke test and final verification

**Files:**
- No new files

- [ ] **Step 1: Reinstall squackit**

Run: `/home/teague/.local/share/venv/bin/pip install -e /mnt/aux-data/teague/Projects/squackit`

- [ ] **Step 2: Manual CLI smoke tests**

Run each and verify:

```bash
squackit tool list
squackit tool view "squackit/**/*.py" ".fn#cli"
squackit tool find "squackit/**/*.py" ".class"
squackit tool find_names "squackit/**/*.py" ".fn"
squackit tool complexity "squackit/**/*.py" ".fn"
squackit --json tool find "squackit/cli.py" ".fn"
squackit tool FindNames "squackit/**/*.py" ".fn"
squackit tool find-names "squackit/**/*.py" ".fn"
squackit tool read_source squackit/cli.py --lines "1-5"
squackit tool project_overview
```

- [ ] **Step 3: Run full test suite**

Run: `FLEDGLING_REPO_PATH=/mnt/aux-data/teague/Projects/source-sextant/main /home/teague/.local/share/venv/bin/pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: smoke test fixes for pluckit tool integration"
```

---

## Summary

| Task | What it builds | New tests |
|---|---|---|
| 1 | executor field, extra_tools, MASKED_BY_PLUCKIT | ~6 |
| 2 | Pluckit tool executors in squackit/tools.py | ~14 |
| 3 | CLI executor dispatch + pluckit tools wired in | ~9 |
| 4 | MCP server executor dispatch + pluckit tools wired in | 0 (regression) |
| 5 | Smoke test and cleanup | 0 (manual) |
