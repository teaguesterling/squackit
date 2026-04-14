# Architecture

## Layering

squackit sits at the top of the fledgling stack, adding stateful intelligence
on top of the stateless query layers below it.

```
Layer 4   Consumers (Claude Code, agents, IDE extensions)
              │
Layer 3b  squackit ─── stateful MCP server + intelligence
              │        smart defaults, caching, truncation,
              │        workflows, prompts, resources
              │
Layer 3a  pluckit ──── fluent Python API (jQuery-like, stateless)
              │        CSS selectors over ASTs, chainable queries
              │
Layer 2   fledgling-python ── thin Python bundler
              │                connect(), attach(), configure()
              │
Layer 1   fledgling ──── SQL macros (language-agnostic)
              │          read_source, doc_outline,
              │          recent_changes, file_diff, ...
              │
Layer 0   DuckDB extensions
              sitting_duck (AST parsing)
              markdown (doc parsing)
              duck_tails (git integration)
              read_lines (file I/O)
```

## Dependency invariants

These are enforced at the package level, not just by convention:

1. **squackit imports pluckit, never fledgling-python.** If squackit needs
   a capability pluckit doesn't expose, pluckit grows the capability.

2. **squackit never constructs SQL strings directly.** It calls tools via
   the fledgling Connection proxy (for fledgling macros) or pluckit's
   fluent API (for pluckit tools).

3. **squackit is the only layer with session state.** Pluckit holds no
   per-call memory. Fledgling-python holds no per-call memory.

4. **squackit is the only layer that knows about MCP.** FastMCP wiring,
   prompt templates, and resource handlers live exclusively in squackit.

5. **Pluckit tools take priority over fledgling equivalents.** When both
   provide a capability, pluckit wins (via the `extra_tools` parameter
   and `MASKED_BY_PLUCKIT` set in `tool_config.py`).

## Module responsibilities

| Module | Role |
|--------|------|
| `cli.py` | Click-based CLI. `squackit mcp serve`, `squackit tool <name>`, `squackit pluck`. Dynamic command generation from the tool registry. |
| `server.py` | FastMCP server wiring. Registers fledgling macros and pluckit tools as MCP tools, defines resources, connects prompts and workflows. |
| `tool_config.py` | `ToolPresentation` dataclass wrapping fledgling `ToolInfo`. `build_tool_registry()` unifies fledgling macros and pluckit tools with priority-based masking. |
| `tools.py` | Pluckit-backed tool executors (`view`, `find`, `find_names`, `complexity`) and their `ToolPresentation` definitions. |
| `defaults.py` | Project inference. Analyzes the codebase at startup to determine `code_pattern`, `doc_pattern`, `main_branch`. Reads config file overrides. |
| `formatting.py` | Token-aware truncation. Head+tail display, omission messages, bypass logic for narrowing parameters. JSON output formatter. |
| `workflows.py` | Compound workflow tools. `explore`, `investigate`, `review`, `search` — each composes multiple fledgling macros into a single briefing. |
| `session.py` | Session state. `SessionCache` (in-memory with TTL) and `AccessLog` (records every tool call). |
| `prompts.py` | MCP prompt templates. `explore`, `investigate`, `review` — pre-load live data into structured workflow instructions. |
| `db.py` | Connection factory. Thin wrapper over `pluckit.Plucker(...).connection`. |

## How a tool call flows

**Fledgling macro tool (e.g., `read_source`):**

```
Agent calls "read_source" via MCP
    │
    ▼
server.py: _register_tool handler
    │
    ├─ Apply smart defaults (defaults.py)
    │
    ├─ Check session cache (session.py)
    │   Cache hit → return cached result with "(cached)" note
    │
    ├─ Execute macro via Connection proxy
    │   con.read_source(file_path=..., lines=...)
    │       │
    │       ▼
    │   fledgling-python → DuckDB → sitting_duck
    │
    ├─ Format result (formatting.py)
    │   Truncate if over limit, add head+tail hints
    │
    ├─ Update cache and access log (session.py)
    │
    └─ Return formatted text to agent
```

**Pluckit tool (e.g., `view`):**

```
Agent calls "view" via MCP
    │
    ▼
server.py: _register_executor_tool handler
    │
    ├─ Call ToolPresentation.executor(source=..., selector=...)
    │       │
    │       ▼
    │   squackit/tools.py: view_executor
    │       │
    │       ▼
    │   Plucker(code=source, plugins=[AstViewer]).view(selector)
    │
    ├─ Type-dispatch formatting
    │   View → markdown | DuckDBPyRelation → table | list → lines
    │
    └─ Return formatted text to agent
```

## What squackit is NOT

- **Not a code editor.** squackit reads and analyzes code; it doesn't
  modify it. Write operations belong to the agent or IDE.

- **Not an LLM.** squackit provides structured data to agents; the
  intelligence is in the agent that consumes the tools.

- **Not a generic MCP framework.** squackit is specifically about
  fledgling's code intelligence macros. For generic MCP servers, use
  [FastMCP](https://github.com/jlowin/fastmcp) directly.

- **Not pluckit.** pluckit is a stateless fluent API for developers.
  squackit is a stateful MCP server for agents. They share the same
  SQL backbone but serve different audiences with different needs.
