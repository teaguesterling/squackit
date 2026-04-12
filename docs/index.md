# squackit

**Semi-QUalified Agent Companion Kit** — the stateful intelligence + MCP server
layer for [fledgling](https://github.com/teaguesterling/fledgling)-equipped
agents.

squackit wraps fledgling's SQL macros (via [pluckit](https://github.com/teaguesterling/pluckit) — [`ast-pluckit`](https://pypi.org/project/ast-pluckit/) on PyPI)
with smart defaults, token-aware output, session caching, compound workflows,
an MCP server, prompt templates, and live resources. It is the Python-side
"cold-start agent support" layer — the opinionated features that don't belong
in fledgling's neutral SQL core.

## What it does

When an AI agent connects to squackit's MCP server, it gets:

- **25+ tools** for reading code, searching definitions, browsing docs, inspecting git history, and running diagnostics — all powered by fledgling's DuckDB macros
- **4 compound workflows** (`explore`, `investigate`, `review`, `search`) that compose multiple tools into single-call briefings
- **3 prompt templates** that pre-load live project data into exploration, debugging, and review workflows
- **5 always-on resources** exposing project overview, diagnostics, docs, git status, and session history
- **Smart defaults** that infer your project's language, doc layout, and main branch so tools work without configuration
- **Token-aware output** with configurable truncation, head+tail display, and automatic bypass when the agent narrows its query
- **Session caching** with per-tool TTL policies and mtime-based invalidation for content tools

## Quick install

```bash
pip install squackit
```

Then start the MCP server:

```bash
squackit
```

Or use it programmatically:

```python
from squackit.server import create_server

mcp = create_server(root="/path/to/project")
mcp.run()
```

See the [Getting Started](quickstart.md) guide for IDE integration and configuration.

## Architecture

```
Layer 4   Consumers (Claude Code, agents, IDE extensions)
Layer 3b  squackit          ← this package
Layer 3a  pluckit           (fluent Python API)
Layer 2   fledgling-python  (Python bundler)
Layer 1   fledgling         (SQL macros)
Layer 0   DuckDB extensions (sitting_duck, markdown, duck_tails, ...)
```

squackit depends on pluckit and never imports fledgling directly. If squackit
needs a capability pluckit doesn't expose, pluckit grows the capability.
See [Architecture](architecture.md) for details.
