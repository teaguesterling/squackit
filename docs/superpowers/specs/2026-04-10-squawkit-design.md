# squackit — Semi-QUalified Agent Companion Kit

**Date:** 2026-04-10
**Status:** Design agreed (brainstorm). Implementation plan pending.
**Scope:** The squackit package as a whole. Cross-package changes in fledgling and pluckit are in separate specs.

## What squackit is

squackit is the stateful intelligence layer for fledgling-equipped agents. It wraps pluckit (and through it, fledgling-python and fledgling's SQL macros) with smart defaults, token-aware output, session caching, workflow objects, an MCP server, prompts, resources, and a kibitzer suggestion engine.

squackit is **a collection of tools**, not a single service. The MCP server is the default entry point, but individual subsystems (cache, access log, defaults, kibitzer) are usable independently.

### Why squackit exists as a separate package

Three concerns that currently live in `fledgling/pro/` don't belong in fledgling itself:

- **Stateful** — SQL macros can't hold a session cache or access log. Whatever owns these has to be Python.
- **MCP-flavored** — prompts, resources, and FastMCP wiring are protocol-specific and shouldn't be carried by a neutral Python bundler or a jQuery-like fluent API.
- **Opinionated** — smart defaults, truncation limits, and kibitzer heuristics are deliberate choices. A notebook user or CLI consumer may not want any of them. Keeping them in a separate package means the lower layers stay usable without adopting the opinions.

Moving them into squackit lets fledgling and fledgling-python stay neutral, lets pluckit stay jQuery-like and stateless, and gives the opinionated "cold-start agent support" concerns their own home with their own release cadence.

## Name

**squackit — Semi-QUalified Agent Companion Kit**. Sibling naming with `pluckit`: verb+it, bird-themed, sardonic register. The backronym:

| Letter | Word |
|---|---|
| **S** | Semi- |
| **QU** | QUalified |
| **A** | Agent |
| **C** | Companion |
| **K** | Kit |
| **IT** | verb-affix, matching pluckit |

"Semi-qualified" is the honest epistemic prefix — the package offers heuristics, not oracles. "Agent Companion" captures the audience (cold-start agents) and role (low-status helper who shows up with whatever's needed). "Kit" matches reality: it's a collection of tools, not a monolithic service.

- **PyPI name:** `squackit`
- **Import name:** `squackit`
- **CLI entry point:** `squackit` (runs the MCP server)

## Layering

```
Layer 4   Consumers (lackpy, agents, humans via CLI)
Layer 3b  squackit              ← this package
Layer 3a  pluckit
Layer 2   fledgling-python
Layer 1   fledgling             (SQL macros)
Layer 0   DuckDB extensions
```

squackit depends on pluckit. It **never** reaches around pluckit to fledgling-python directly; if it needs a capability pluckit doesn't expose, pluckit grows the capability. This is an invariant, not a guideline — see "Dependency chain invariants" below.

## Features

### Smart defaults

Project inference runs on server startup and caches the results for the session.

| Default | Source | Fallback |
|---|---|---|
| `code_pattern` | `project_overview()` dominant language | `'**/*.py'` |
| `doc_pattern` | scan for `docs/`, `documentation/`, `doc/` | `'docs/**/*.md'` |
| `main_branch` | git HEAD | `'main'` |

Overrides live in `.squackit/config.toml` at the project root:

```toml
[defaults]
code_pattern = "src/**/*.rs"
doc_pattern = "documentation/**/*.md"
main_branch = "develop"
```

Explicit tool parameters always win over inferred defaults. The precedence is: explicit call argument > config file override > inferred default > hard-coded fallback.

### Token-aware output

Every tool has configurable truncation:

| Tool type | Default limit | Parameter |
|---|---|---|
| Content tools (`read_source`, `file_diff`) | 200 lines | `max_lines` |
| Discovery tools (`find_definitions`, `list_files`) | 50 rows | `max_results` |
| Git tools (`file_changes`, `recent_changes`) | 20–25 rows | `max_results` |

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

**Bypass:** providing a narrowing parameter (`lines`, `match`, `name_pattern`) disables truncation — the agent is already being specific, so the cap gets out of the way.

### Workflow objects

Python objects that wrap fledgling's new workflow SQL macros (`explore_query`, `investigate_query`, `review_query`, `search_query`) with:

- Cache lookup before running the query
- Briefing assembly (unpacking the struct result into formatted markdown)
- Hint emission ("you already called this 2 minutes ago — returning cached")
- Access log write

Architecturally: the SQL macros are the engines, the Python workflow objects are the operator cabins. The split is deliberate — the SQL is reusable by any consumer; the Python is specific to squackit's opinionated output shape.

Each workflow object has the same four-method shape: `run(**args)`, `_cache_key(**args)`, `_format(result)`, `_hint(cache_state)`. This makes adding a new workflow a mechanical operation.

### Session state

**Cache.** In-memory, keyed by `(tool_name, frozen_args)`. TTL varies by tool:

- `project_overview`, `explore_query` — session lifetime
- `working_tree_status` — 10 seconds
- Content tools — invalidate on file mtime change

**Access log.** Every tool call is recorded: tool name, arguments, row count, latency, timestamp, cache-hit flag. Written to disk for cross-process consumption (see Persistence).

### MCP resources

Always-available context the agent can read without making a tool call:

| URI | Content |
|---|---|
| `squackit://project` | Languages, file counts, top-level directory listing |
| `squackit://diagnostics` | Version, profile, modules, extensions, inferred defaults |
| `squackit://docs` | Documentation outline (all markdown files) |
| `squackit://git` | Branches, recent commits, working tree status |
| `squackit://session` | Access log summary for the current session |

### Prompt templates

- `explore(path?)` — exploration instructions with project overview pre-filled
- `investigate(symptom)` — debugging workflow with relevant definitions pre-found
- `review(from_rev?, to_rev?)` — review checklist with change summary pre-loaded

### Kibitzer

The kibitzer is **one feature among several** in squackit's collection of tools, not the package's primary identity. It's the suggestion engine that observes tool-call patterns and emits recommendations inline with tool responses.

Observation runs on each MCP tool call. Patterns and suggestions:

| Pattern observed | Suggestion |
|---|---|
| 3+ ReadLines on same file with different `match` | "Try FindInAST for structural search" |
| ReadLines without `lines` on file > 200 lines | "This file has N lines. Use `lines='N-M'` to narrow." |
| `find_definitions` returning 50+ results | "Use `name_pattern` to narrow" |
| Repeated identical query | Cache returns with a note; no re-query |

Suggestions are emitted as part of the tool's response, not as separate messages. The agent sees them inline without any extra protocol dance.

**Relationship to lackpy's kibitzer.** Lackpy has its own kibitzer for a different role: the correction engine and outcome tracker for delegated sub-agent episodes (parent agent → sub-agent in a reduced scope). Lackpy's kibitzer consumes squackit's access log to score episodes. They are different kibitzers with different audiences and different responsibilities. This package does not try to be both.

## Persistence

The access log is written to disk so external consumers (lackpy's kibitzer, user-facing dashboards) can read it without sharing process state with the squackit MCP server.

**Format:** DuckDB database at `~/.squackit/sessions/<session_id>.duckdb`. Rationale: DuckDB is already in-process, the log is query-friendly (agents and kibitzers want to ask questions like "which tools did this session call most often"), and existing consumers (lackpy) already have DuckDB as a dependency. SQLite and JSONL were considered — SQLite lacks the analytical query story, JSONL is write-cheap but read-expensive.

**Schema (provisional):**

```sql
CREATE TABLE access_log (
    session_id TEXT,
    tool_name TEXT,
    arguments JSON,
    row_count INT,
    latency_ms DOUBLE,
    timestamp TIMESTAMP,
    cache_hit BOOLEAN,
    output_truncated BOOLEAN,
    suggestions_emitted JSON
);
```

**Session boundaries.** One session per MCP server process. The `session_id` is generated at startup (UUID v4) and stamped on every row.

**Project-scoped override.** A project can set `[persistence] session_dir = ".squackit/sessions"` in `.squackit/config.toml` to write sessions alongside the project instead of in the user home directory. Useful for CI runs and reproducible experiments.

## Package layout

```
squackit/
├── pyproject.toml
├── README.md
├── CLAUDE.md                    — squackit conventions
├── src/squackit/
│   ├── __init__.py              — public API exports
│   ├── __main__.py              — `python -m squackit` entry point
│   ├── server.py                — FastMCP server wiring
│   ├── defaults.py              — project inference
│   ├── formatting.py            — truncation, briefings
│   ├── workflows.py             — workflow objects wrapping SQL macros
│   ├── session.py               — SessionCache, AccessLog, persistence
│   ├── prompts.py               — MCP prompt templates
│   ├── resources.py             — MCP resource providers
│   └── kibitzer/
│       ├── __init__.py
│       ├── observer.py          — watches tool calls
│       └── rules.py             — pattern → suggestion rules
├── tests/
│   ├── test_defaults.py
│   ├── test_formatting.py
│   ├── test_workflows.py
│   ├── test_session.py
│   ├── test_resources.py
│   ├── test_prompts.py
│   ├── test_server.py
│   └── test_kibitzer.py
└── docs/superpowers/
    ├── specs/
    │   └── 2026-04-10-squackit-design.md   (this file)
    └── plans/
```

## Dependencies

**Runtime:**

- `pluckit` — fluent Python API over fledgling-python
- `fastmcp` — MCP server framework
- `duckdb` — via fledgling-python transitively

`fledgling-python` is pulled in transitively through pluckit. squackit does not import it directly.

**Dev:**

- `pytest`
- Whatever test infrastructure fledgling uses (for compatibility of shared fixtures, if any)

## Dependency chain invariants

These are invariants, not guidelines:

1. squackit imports `pluckit`, **not** `fledgling_python`.
2. squackit never constructs SQL strings; it calls pluckit chains or invokes fledgling SQL macros via pluckit's macro-call proxy.
3. squackit is the only layer with session state. Pluckit holds no per-call memory. Fledgling-python holds no per-call memory.
4. squackit is the only layer that knows about MCP as a protocol.

When one of these invariants would be violated, the fix is to grow pluckit's API, not to add escape hatches in squackit.

## Open questions

- **Kibitzer as feature vs separate package.** Could be split into `squackit-kibitzer` if it grows independent release velocity. Initial release bundles it; splitting is reversible.
- **Config file discovery.** Walk up from cwd for `.squackit/config.toml`, walk up from explicit `session_root`, or both? Lean: walk up from session_root if provided, else cwd. Same rule as fledgling's `.fledgling-init.sql` discovery.
- **Truncation parameter name collisions.** Agents may call tools with `max_lines` already as a semantic parameter (distinct from the truncation cap). Need to audit fledgling's MCP tool parameter names and reserve `_max_lines`/`_max_results` if needed. Detail for implementation, not design.

## Cross-references

- **fledgling reorg:** `/mnt/aux-data/teague/Projects/source-sextant/main/docs/superpowers/specs/2026-04-10-fledgling-reorg-design.md`
- **pluckit integration:** `~/Projects/pluckit/main/docs/superpowers/specs/2026-04-10-fledgling-python-integration-design.md`
- **lackpy reorg-prep:** `~/Projects/lackpy/trees/feature/interpreter-plugins/docs/superpowers/specs/2026-04-10-sql-macro-reorg-prep.md`
