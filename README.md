# squackit

[![PyPI](https://img.shields.io/pypi/v/squackit)](https://pypi.org/project/squackit/)
[![Docs](https://readthedocs.org/projects/squackit/badge/?version=latest)](https://squackit.readthedocs.io/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Semi-QUalified Agent Companion Kit.** A code intelligence toolkit that
works two ways: as an MCP server for AI agents, and as a CLI for humans.

Built on [pluckit](https://github.com/teaguesterling/pluckit) (CSS selectors
over ASTs) and [fledgling](https://github.com/teaguesterling/fledgling)
(SQL macros over DuckDB).

## Install

```bash
pip install squackit
```

## CLI usage

```bash
# Run any tool from the shell
squackit tool list
squackit tool view "src/**/*.py" ".fn#main"
squackit tool find_names "**/*.py" ".class"
squackit tool complexity "src/**/*.py" ".fn"

# JSON output for scripting
squackit --json tool find "src/**/*.py" ".fn"

# Pluckit chain queries
squackit pluck "src/**/*.py" find .fn containing cache names
squackit pluck "src/api.py" find .class#Handler children find .fn names

# Start the MCP server
squackit mcp serve
```

Tool names resolve in three conventions: `find_names`, `find-names`, `FindNames`.
Tab completion is built in (`eval "$(_SQUACKIT_COMPLETE=bash_source squackit)"`).

## What agents get via MCP

- **~35 tools** — CSS-selector code queries (via pluckit), file I/O, git history,
  doc navigation, conversation analytics, and diagnostics. The exact set is dynamic
  (fledgling macros + pluckit tools + pluckins); a full install exposes ~40 MCP tools
  including the workflows below.
- **4 compound workflows** — `explore`, `investigate`, `review`, `search`
- **3 prompt templates** — pre-loaded with live project data
- **5 resources** — project overview, docs, git status, session log, diagnostics
- **`pluck` tool** — full pluckit chain grammar for multi-step AST queries,
  with mutation safety (blocked by default, opt-in via `allow_mutations=true`)
- **Smart defaults** — infers language, doc layout, main branch automatically
- **Token-aware output** — configurable truncation with `max_results`/`max_lines`

## Architecture

```
Layer 4   Consumers (Claude Code, agents, IDE extensions)
              │
Layer 3b  squackit ─── CLI + MCP server + intelligence
              │        smart defaults, caching, truncation,
              │        workflows, pluckit tools, mutation safety
              │
Layer 3a  pluckit ──── fluent Python API (CSS selectors over ASTs)
              │
Layer 2   fledgling ── SQL macros + Python bundler
              │
Layer 0   DuckDB extensions (sitting_duck, markdown, duck_tails, read_lines)
```

Pluckit tools take priority over fledgling equivalents when both provide a
capability (e.g., pluckit's `find` supersedes fledgling's `find_definitions`).

> **Note:** pluckit is published on PyPI as
> [`ast-pluckit`](https://pypi.org/project/ast-pluckit/). The import name is `pluckit`.

## Documentation

Full docs at **[squackit.readthedocs.io](https://squackit.readthedocs.io/)**.

## License

Apache 2.0
