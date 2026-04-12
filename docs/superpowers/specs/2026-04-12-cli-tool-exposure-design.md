# Design: CLI Tool Exposure & ToolPresentation

**Date:** 2026-04-12
**Status:** Draft

## Summary

Expose squackit's tools as CLI subcommands under `squackit tool` (alias `squackit t`), with dynamic discovery from fledgling's `ToolInfo` metadata. Refactor squackit's scattered per-tool configuration dicts into a single `ToolPresentation` dataclass that drives both MCP and CLI registration. Design for multiple tool sources (fledgling macros, pluckit tools, squackit workflows) with a plugin-like architecture.

## Goals

1. `squackit tool <name> [positional...] [--flags...]` runs any tool from the terminal
2. Output defaults to markdown for humans; `--json` flag for structured output
3. All three naming conventions resolve: `find_definitions`, `find-definitions`, `FindDefinitions`
4. Tab completion works for all tool names and their aliases
5. Replace 8+ scattered dicts in `server.py` with a single per-tool config object
6. Support multiple tool sources with priority-based override

## Non-goals

- Exposing MCP resources or prompts as CLI commands (future)

## Fledgling ToolInfo API (landed in v0.8.2)

`fledgling.tools.ToolInfo` is now a public dataclass. `Tools.__iter__` yields `ToolInfo` objects, `Tools.get(name)` returns one.

```python
info = con._tools.get("find_definitions")

# Macro-level (always populated from catalog)
info.macro_name         # 'find_definitions'
info.params             # ['file_pattern', 'name_pattern']  (macro param order)
info.required_params    # ['file_pattern']                  (must provide)
info.optional_params    # ['name_pattern']                  (has default)

# MCP registry-level (populated when duckdb_mcp is loaded, None otherwise)
info.tool_name          # 'FindDefinitions' or None
info.description        # 'AST-based definition search...' or None
info.parameters_schema  # {'file_pattern': {'type': 'string', ...}} or None
info.required           # ['file_pattern'] or None
info.format             # 'markdown' or None
info.sql_template       # 'SELECT * FROM find_definitions(...)' or None
```

### Catalog fallback behavior

When duckdb_mcp is not loaded, `required_params` is derived from macro analysis. Currently all params are marked required on the catalog path (DuckDB doesn't expose defaults for table macros). squackit must override `required_params` for tools where this is wrong.

## Architecture

### Tool sources and priority

Multiple sources can provide tools. When sources overlap, higher-priority sources win:

```
pluckit tools  >  fledgling MCP-published  >  fledgling catalog  >  squackit workflows
```

The architecture uses a plugin-like pattern ("pluckins") where each source yields `ToolInfo`-compatible objects. For now, the implementation is a simple ordered list of iterables; the plugin system can formalize later.

### ToolPresentation (composition over ToolInfo)

```python
@dataclass
class ToolPresentation:
    """Wraps fledgling ToolInfo with squackit's presentation/UX config."""

    info: ToolInfo

    # Squackit presentation overrides (None = delegate to info)
    alias: str | None = None
    format_override: Literal["table", "text"] | None = None
    required_override: list[str] | None = None
    max_rows: int | None = None
    max_lines: int | None = None
    range_params: frozenset[str] = frozenset()
    cache_ttl: int | None = None
    cache_mtime_params: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.alias or self.info.tool_name or self.info.macro_name

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
        return self.info.required or self.info.required_params

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
        return self.info.description or f"Query: {self.name}({', '.join(self.params)})"

    @property
    def parameters_schema(self) -> dict | None:
        return self.info.parameters_schema
```

### Overrides (transitional)

A single `_OVERRIDES` dict captures squackit-specific per-tool config. Intended to shrink over time as fledgling metadata improves. Keys are macro names:

```python
_OVERRIDES: dict[str, dict] = {
    "pss_render": {
        "alias": "select_code",
        "format_override": "text",
    },
    "read_source": {
        "format_override": "text",
        "required_override": ["file_path"],
        "max_lines": 200,
        "range_params": frozenset({"lines", "match"}),
        "cache_ttl": 300,
        "cache_mtime_params": ("file_path",),
    },
    ...
}
```

### Registration flow

```python
def _build_tool_registry(tools_iterable, skip=None) -> dict[str, ToolPresentation]:
    """Build the tool registry from ToolInfo sources + squackit overrides."""
    skip = skip or set()
    registry = {}
    for tool_info in tools_iterable:
        if tool_info.macro_name in skip:
            continue
        overrides = _OVERRIDES.get(tool_info.macro_name, {})
        presentation = ToolPresentation(info=tool_info, **overrides)
        registry[presentation.name] = presentation
    return registry
```

One registry feeds both MCP and CLI registration.

### CLI structure

```
squackit                          Show help
squackit --version                Show version
squackit --json                   Global flag: JSON output for subcommands
squackit mcp serve [opts]         Start MCP server
squackit tool list                List available tools
squackit tool <name> [args]       Run a tool
squackit t <name> [args]          Alias for 'tool'
```

### Tool name resolution

All three naming conventions resolve to the same tool:
- `find_definitions` (underscore, canonical)
- `find-definitions` (kebab-case)
- `FindDefinitions` (CamelCase)

Implementation: a custom `click.Group` subclass that normalizes command names on lookup and returns all forms for tab completion.

### Positional parameter rules

**MCP-published tools** (ToolInfo has `required` from registry):
- Positional params = `ToolInfo.required`, in registry order
- Optional params are always `--flags`

**Catalog-fallback tools** (ToolInfo from catalog scan):
- Positional params = all params, in macro definition order
- Required come first, then optional
- User can skip positional by using `--name value`

Example:
```bash
# read_source: required=[file_path], optional=[lines, ctx, match]
squackit tool read_source src/main.py                    # positional required
squackit tool read_source src/main.py --lines "10-20"    # named optional
squackit tool read_source src/main.py "10-20" 3          # positional optional (catalog)

# find_definitions: required=[file_pattern], optional=[name_pattern]
squackit t find-definitions "**/*.py" "%test%"
```

### Dynamic Click command generation

Each tool becomes a Click command generated at CLI startup:

```python
def _make_tool_command(presentation: ToolPresentation, con) -> click.Command:
    params = []
    positional = _get_positional_params(presentation)
    for p in positional:
        required = p in presentation.required
        params.append(click.Argument([p], required=required))
    for p in presentation.params:
        if p not in positional:
            params.append(click.Option([f"--{p}"], default=None))

    @click.pass_context
    def callback(ctx, **kwargs):
        result = _execute_tool(con, presentation, kwargs)
        _format_output(ctx, result, presentation)

    return click.Command(
        name=presentation.name,
        help=presentation.description,
        params=params,
        callback=callback,
    )
```

### Output formatting

- **Default:** Markdown tables for structured data, plain text for text-format tools
- **`--json`:** JSON array of objects (`[{col: value, ...}, ...]`)

```bash
squackit tool find_definitions "**/*.py"           # markdown table
squackit --json tool find_definitions "**/*.py"    # JSON array
squackit tool read_source src/main.py              # plain text
squackit --json tool read_source src/main.py       # JSON lines
```

### `squackit tool list`

```bash
$ squackit tool list
Name                 Description
find_definitions     Find function, class, and module definitions...
code_structure       Structural overview with complexity metrics...
...

$ squackit --json tool list
[{"name": "find_definitions", "params": [...], "required": [...], ...}, ...]
```

## Migration from scattered dicts

| Current dict | Replacement | Source |
|---|---|---|
| `_DESCRIPTIONS` | `ToolInfo.description` | fledgling |
| `_SKIP` | Exclusion set (remains in squackit, shrinks as fledgling curates) | squackit |
| `_ALIASES` | `ToolPresentation.alias` via `_OVERRIDES` | squackit |
| `_TEXT_FORMAT` | `ToolInfo.format` / `ToolPresentation.format_override` | fledgling + squackit |
| `_NUMERIC_PARAMS` | `ToolInfo.parameters_schema` JSON Schema types | fledgling |
| `_RANGE_PARAMS` | `ToolPresentation.range_params` via `_OVERRIDES` | squackit |
| `_MAX_LINES`/`_MAX_ROWS` | `ToolPresentation.max_lines/max_rows` via `_OVERRIDES` | squackit |
| `CACHE_POLICY` | `ToolPresentation.cache_ttl/cache_mtime_params` via `_OVERRIDES` | squackit |

## Files to create/modify

| File | Action |
|---|---|
| `squackit/tool_config.py` | **New** — `ToolPresentation`, `_OVERRIDES`, `_SKIP`, registry builder |
| `squackit/cli.py` | **Modify** — add `tool`/`t` group, `tool list`, dynamic commands, `--json` flag |
| `squackit/server.py` | **Modify** — replace scattered dicts with `ToolPresentation` registry |
| `squackit/formatting.py` | **Modify** — add JSON output formatter |
| `tests/test_cli.py` | **New** — CLI tool command tests |
| `tests/test_tool_config.py` | **New** — ToolPresentation registry tests |

## Future directions

- **Plugin system ("pluckins")** — formalize tool source registration with priority, allowing pluckit, fledgling, and squackit workflows to contribute tools through a common interface
- **Eliminate `_OVERRIDES`** — as fledgling metadata improves (format, descriptions, required) and the plugin system matures, squackit-specific overrides should shrink toward zero
- **Workflow tools via CLI** — `explore`, `investigate`, `review`, `search` exposed through the same `squackit tool` interface
- **Config file** — per-tool overrides in `.squackit/config.toml` instead of code
