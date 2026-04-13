# Design: Pluckit Tool Integration

**Date:** 2026-04-12
**Status:** Approved

## Summary

Integrate pluckit as a tool source in squackit's tool namespace, exposing `view`, `find`, `find_names`, and `complexity` as first-class tools alongside fledgling macros. Pluckit tools take priority over fledgling equivalents, masking redundant tools. ToolPresentation gains an `executor` field to support tools with non-standard execution paths.

## Goals

1. Four pluckit-backed tools in `squackit tool`: `view`, `find`, `find_names`, `complexity`
2. Pluckit tools mask fledgling equivalents (`select_code`, `find_definitions`, `code_structure`, `complexity_hotspots`)
3. ToolPresentation executor pattern supports different return types (relation, View, list)
4. Both CLI and MCP paths work with the new tools

## Dependencies

- pluckit v0.7.1+ with `Selection.relation`, `View.relation`, `View.tabular` properties (landed)
- pluckit `Selection.__str__`, `__repr__`, `__iter__`, `__len__`, `__bool__`, `_parent` tracking (landed)
- fledgling ToolInfo (v0.8.2, already in use)

## Architecture

### New file: `squackit/tools.py`

Defines pluckit-backed tool functions and their metadata. Each tool has:
- A function that wraps pluckit calls
- A hand-crafted `ToolInfo` for metadata
- A `ToolPresentation` with an `executor` pointing to the function

```python
# squackit/tools.py

from fledgling.tools import ToolInfo
from squackit.tool_config import ToolPresentation


def _make_plucker():
    """Create a Plucker with AstViewer for tool execution."""
    from pluckit import Plucker
    from pluckit.plugins.viewer import AstViewer
    return Plucker(plugins=[AstViewer])


def view_executor(source: str, selector: str) -> View:
    """Execute a view query, returning rendered source code."""
    p = _make_plucker()
    return p.source(source).view(selector)


def find_executor(source: str, selector: str) -> DuckDBPyRelation:
    """Execute a find query, returning matched AST nodes as a relation."""
    p = _make_plucker()
    return p.source(source).find(selector).relation


def find_names_executor(source: str, selector: str) -> list[str]:
    """Execute a find query, returning just the names."""
    p = _make_plucker()
    return p.source(source).find(selector).names()


def complexity_executor(source: str, selector: str) -> DuckDBPyRelation:
    """Execute a find query with complexity metrics."""
    p = _make_plucker()
    sel = p.source(source).find(selector)
    # Project to useful columns including descendant_count as complexity
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


# Tool definitions

VIEW_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="view",
        params=["source", "selector"],
        description="View source code matching CSS selectors. Returns rendered markdown with file headings and source blocks.",
        required=["source", "selector"],
    ),
    format_override="text",
    executor=view_executor,
)

FIND_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="find",
        params=["source", "selector"],
        description="Find AST nodes matching CSS selectors. Returns file paths, names, line ranges.",
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

### ToolPresentation changes

Add `executor` field to the dataclass:

```python
@dataclass
class ToolPresentation:
    ...
    executor: Callable | None = None
```

When `executor` is not None, the tool execution path uses it instead of the default `getattr(con, macro_name)(**kwargs)` pattern.

### Executor return types

The executor callable returns one of:

| Return type | CLI formatting | MCP formatting |
|---|---|---|
| `DuckDBPyRelation` | `.columns`/`.fetchall()` → table or JSON | Same → markdown table or text |
| `View` | `.markdown` for text, `.tabular` for JSON | `.markdown` as string result |
| `list[str]` | One name per line, JSON as array | Newline-joined string |
| `(cols, rows)` tuple | Direct to formatter | Direct to formatter |

The formatting layer checks the return type and dispatches accordingly. This happens in both `_make_tool_command` (CLI) and `_register_tool` (MCP).

### Registry integration

`build_tool_registry` accepts `extra_tools` with higher priority:

```python
def build_tool_registry(tools_iterable, skip=None, extra_tools=None):
    skip = skip if skip is not None else SKIP
    registry = {}

    # Extra tools register first (higher priority)
    if extra_tools:
        for tp in extra_tools:
            registry[tp.name] = tp

    # Fledgling tools: skip if name already taken by extra tools
    for tool_info in tools_iterable:
        if tool_info.macro_name in skip:
            continue
        overrides = OVERRIDES.get(tool_info.macro_name, {})
        presentation = ToolPresentation(info=tool_info, **overrides)
        if presentation.name not in registry:
            registry[presentation.name] = presentation

    return registry
```

### Fledgling masking

When pluckit tools are registered, these fledgling tools are naturally masked by the "name not already taken" check. For tools with different names (e.g., pluckit `find` vs fledgling `find_definitions`), we add the fledgling macro names to the SKIP set conditionally:

```python
# In tool_config.py
MASKED_BY_PLUCKIT = {
    "pss_render",           # masked by view (select_code alias)
    "find_definitions",     # masked by find
    "code_structure",       # masked by find
    "complexity_hotspots",  # masked by complexity
}
```

The `select_code` alias (from `pss_render`) is masked by `view`. `find_definitions` and `code_structure` are masked by `find`. `complexity_hotspots` is masked by `complexity`.

### CLI execution path

`_make_tool_command` checks for `executor`:

```python
def callback(click_ctx, **kwargs):
    if presentation.executor:
        result = presentation.executor(**filtered)
        # Type-dispatch formatting
        if isinstance(result, View):
            ...
        elif hasattr(result, 'columns'):  # DuckDB relation
            ...
        elif isinstance(result, list):
            ...
    else:
        # Existing macro path
        macro = getattr(con, presentation.macro_name)
        ...
```

### MCP execution path

`_register_tool` in server.py similarly checks for `executor` on the ToolPresentation. When present, the async tool function calls the executor instead of the macro.

### Server and CLI integration

In `create_server` and `_get_registry` (CLI), import pluckit tools:

```python
from squackit.tools import PLUCKIT_TOOLS

registry = build_tool_registry(con._tools, extra_tools=PLUCKIT_TOOLS)
```

## Files to create/modify

| File | Action |
|---|---|
| `squackit/tools.py` | **New** — pluckit tool executors and PLUCKIT_TOOLS list |
| `squackit/tool_config.py` | **Modify** — add `executor` field, `extra_tools` param, `MASKED_BY_PLUCKIT` |
| `squackit/cli.py` | **Modify** — executor dispatch in `_make_tool_command`, import PLUCKIT_TOOLS in `_get_registry` |
| `squackit/server.py` | **Modify** — executor dispatch in `_register_tool`, import PLUCKIT_TOOLS in `create_server` |
| `tests/test_tools.py` | **New** — pluckit tool executor tests |
| `tests/test_cli_tools.py` | **Modify** — add tests for pluckit tools via CLI |

## Testing

- Unit tests for each executor function (returns correct type, handles errors)
- Integration tests via CLI (CliRunner): `squackit tool view "**/*.py" ".fn"`, JSON output
- Integration tests via MCP: verify pluckit tools are registered on the server
- Verify masked fledgling tools are NOT in the registry when pluckit tools are present
- Regression: full existing test suite passes
