# Configuration

## Smart defaults

squawkit infers project settings at startup by analyzing the codebase:

| Default | How it's inferred | Fallback |
|---------|-------------------|----------|
| `code_pattern` | Dominant language from `project_overview()` | `**/*.py` |
| `doc_pattern` | Scans for `docs/`, `documentation/`, `doc/` directories | `docs/**/*.md` |
| `main_branch` | Git HEAD reference | `main` |

These defaults are used whenever a tool parameter is omitted. For example,
`find_definitions()` with no `file_pattern` uses the inferred `code_pattern`.

## Config file

Override inferred defaults with a TOML config file at the project root:

```
.squawkit/config.toml
```

Or the legacy path:

```
.fledgling-python/config.toml
```

### Example

```toml
[defaults]
code_pattern = "src/**/*.rs"
doc_pattern = "documentation/**/*.md"
main_branch = "develop"
```

## Precedence

From highest to lowest priority:

1. **Explicit tool parameter** — the agent passes `file_pattern="src/**/*.go"` in the tool call
2. **Config file override** — `.squawkit/config.toml` sets `code_pattern`
3. **Inferred default** — squawkit analyzes the project at startup
4. **Hard-coded fallback** — `**/*.py`, `docs/**/*.md`, `main`

## Session cache

Tools cache their results in-memory for the duration of the MCP session.
Cache policies vary by tool:

| Tool category | TTL | Invalidation |
|---------------|-----|-------------|
| `project_overview`, `explore` | Session lifetime | Never (run once) |
| `find_definitions`, `code_structure` | 5 minutes | Time-based |
| `read_source`, `read_context` | 5 minutes | File mtime change |
| `doc_outline` | Session lifetime | Never |
| `recent_changes` | 30 seconds | Time-based |
| `working_tree_status` | 10 seconds | Time-based |

When a cached result is returned, squawkit appends a note:
`"(cached — N seconds ago)"`.

## Token-aware truncation

Every tool has configurable output limits:

| Tool type | Default limit | Parameter |
|-----------|---------------|-----------|
| Content tools (`read_source`, `file_diff`) | 200 lines | `max_lines` |
| Discovery tools (`find_definitions`, `list_files`) | 50 rows | `max_results` |
| Git tools (`file_changes`, `recent_changes`) | 20-25 rows | `max_results` |

Truncated output shows head + tail with a hint:

```
  1  import os
  2  import sys
  ...
--- omitted 1847 of 2000 lines ---
Use lines='N-M' to see a range, or match='keyword' to filter.
1996      return result
  ...
```

**Automatic bypass:** providing a narrowing parameter (`lines`, `match`,
`name_pattern`) disables truncation. The agent is already being specific,
so the cap gets out of the way.

## Environment variables

| Variable | Description |
|----------|-------------|
| `FLEDGLING_REPO_PATH` | Override fledgling repo path for test data discovery |

## create_server() parameters

When using squawkit programmatically:

```python
from squawkit.server import create_server

mcp = create_server(
    name="fledgling",       # MCP server name
    root="/path/to/project", # Project root (default: cwd)
    init=None,               # Init file: None=auto, False=skip, path=explicit
    modules=None,            # SQL modules to load (default: all for profile)
    profile="analyst",       # Fledgling security profile
)
```
