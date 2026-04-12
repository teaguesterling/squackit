# squackit

[![PyPI](https://img.shields.io/pypi/v/squackit)](https://pypi.org/project/squackit/)
[![Docs](https://readthedocs.org/projects/squackit/badge/?version=latest)](https://squackit.readthedocs.io/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Semi-QUalified Agent Companion Kit.** The stateful intelligence + MCP server
layer for [fledgling](https://github.com/teaguesterling/fledgling)-equipped
agents.

squackit wraps fledgling's SQL macros (via
[pluckit](https://github.com/teaguesterling/pluckit) — `pip install ast-pluckit`) with smart defaults,
token-aware output, session caching, compound workflows, an MCP server,
prompt templates, and live resources.

## Install

```bash
pip install squackit
```

## Run

```bash
squackit
```

Starts the FastMCP server on stdio. Connect it to Claude Code, Cursor, or any
MCP-compatible client.

## What agents get

- **25+ tools** — code search, AST analysis, doc browsing, git history, diagnostics
- **4 compound workflows** — `explore`, `investigate`, `review`, `search`
- **3 prompt templates** — pre-loaded with live project data
- **5 resources** — always-on project overview, docs, git status, session log
- **Smart defaults** — infers language, doc layout, main branch automatically
- **Token-aware output** — truncation with head+tail hints, automatic bypass

## Architecture

```
squackit → ast-pluckit → fledgling-python → fledgling (SQL) → DuckDB extensions
```

> **Note:** pluckit is published on PyPI as
> [`ast-pluckit`](https://pypi.org/project/ast-pluckit/). The Python import
> name is still `pluckit`.

squackit is the opinionated top layer. It adds session state, MCP protocol,
and intelligence heuristics on top of the stateless query layers below it.

## Documentation

Full docs at **[squackit.readthedocs.io](https://squackit.readthedocs.io/)**.

## License

Apache 2.0
