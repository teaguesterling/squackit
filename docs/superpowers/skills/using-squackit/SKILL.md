---
name: using-squackit
description: Use when squackit's MCP tools are available and you need to read, navigate, or modify a codebase. Prefer squackit's structured tools over Read/Grep/Glob for code intelligence.
---

# Using Squackit

## Overview

Squackit is a code intelligence MCP server. When it's available (you'll see `mcp__squackit__*` tools), use it as your primary surface for understanding code instead of raw file reading.

**Core principle:** squackit returns *structured* code knowledge — AST nodes, function bodies with line ranges, semantic diffs, call graphs. Grep and Read give you bytes; squackit gives you facts.

## When to use squackit vs. other tools

| Task | Prefer |
|---|---|
| "What does this codebase do?" | `mcp__squackit__explore` |
| "Show me function X" | `mcp__squackit__view` (CSS selector) |
| "Where is X defined?" | `mcp__squackit__find_names` or `find` |
| "What calls this function?" | `mcp__squackit__investigate` |
| "Review my changes" | `mcp__squackit__review` |
| "Read this specific file range" | `mcp__squackit__read_source` (caches + truncates) |
| "Find the most complex functions" | `mcp__squackit__complexity` |
| "Multi-step AST query" | `mcp__squackit__pluck` |
| "Search code + docs + git at once" | `mcp__squackit__search` |

Fall back to Grep/Read when:
- Searching non-code files (logs, data, binaries)
- The file isn't in a language squackit parses
- squackit returns `(no results)` or `(no data)`
- squackit tools fail with `ModuleNotFoundError` or `ImportError` — the MCP server is stale; report the error, fall back to Read/Grep, and note the server needs restarting

## Anti-patterns

**Don't Read a whole file when you want one function.**
`view` with a CSS selector returns the exact function rendered in markdown with line numbers. Reading the whole file wastes tokens.

```
❌ Read(file_path="src/auth.py")  # 200 lines to get one function
✅ view(source="src/auth.py", selector=".fn#validate_token")
```

**Don't Grep for function definitions.**
Grep matches text; `find_names` matches AST nodes. Grep will hit `# def foo` in comments and `"def foo"` in strings; `find_names` gives you the real definitions.

```
❌ Grep("def validate_token", type="py")
✅ find_names(source="**/*.py", selector=".fn#validate_token")
```

**Don't use `explore` as a first step for every task.**
`explore` is designed for first-contact on an unfamiliar codebase. For focused work, go straight to `investigate`, `view`, or `find`.

## Tool categories

### Discovery (use these first)
- `explore` — first-contact briefing: languages, key definitions, docs, recent activity
- `project_overview` — file counts by language
- `list_files` — find files by glob

### Reading code
- `view` — render source by CSS selector (best for functions/classes)
- `read_source` — file lines with range, context, match filter
- `read_context` — lines centered on a given line number

### Searching
- `find` — AST nodes matching a selector (full metadata)
- `find_names` — just the names (lighter)
- `search` — multi-source: definitions + call sites + docs + conversations
- `complexity` — selector + ranked by complexity

### Understanding
- `investigate` — definition + source + callers + callees in one call
- `call_graph` — all calls within a file pattern
- `changed_function_summary` — changed functions ranked by complexity

### Git
- `recent_changes` — commit history (no per-file filter; use `file_diff` or `changed_function_summary` for file-scoped history)
- `file_changes` — files changed between two revisions (not per-file commit log)
- `file_diff` — line-level unified diff
- `structural_diff` — semantic diff (added/removed/modified definitions)
- `file_at_version` — file content at a revision
- `working_tree_status` — uncommitted changes
- `branch_list`, `tag_list`

### Documentation
- `doc_outline` — markdown section outlines
- `read_doc_section` — specific section by ID

### Modification (use carefully)
- `pluck` with `allow_mutations=true` — rename, replaceWith, wrap, etc.

See `refactoring-with-squackit` for the mutation workflow.

## CSS selectors (pluckit syntax)

Squackit's `view`, `find`, `find_names`, `complexity` all take CSS-style selectors over ASTs:

| Selector | Matches |
|---|---|
| `.fn` | Function definitions |
| `.class` | Class definitions |
| `.call` | Call expressions |
| `#name` | By name (e.g. `.fn#validate_token`) |
| `.class > .fn` | Methods directly inside a class |
| `.fn:has(.call#old_api)` | Functions that call `old_api` |
| `.class[name*="Test"]` | Classes with "Test" in their name |

Combinators and pseudo-classes come from the pluckit plugin system. Start simple — `.fn#name` and `.class` cover 80% of use cases.

## Common workflows

**Starting on unfamiliar code:**
```
explore() → identify key files
investigate(name="X") → understand one piece
view(selector=".fn#X") → read the source
```
See `exploring-unfamiliar-code` for details.

**Building a multi-step query:**
```
pluck(argv="**/*.py find .class containing cache names")
# → all class names that contain "cache" in their body
```
See `pluck-chains` for grammar and patterns.

**Refactoring:**
```
# Preview with find
find(source="src/**/*.py", selector=".fn#old_name")
# Apply with pluck + allow_mutations
pluck(argv="src/**/*.py find .fn#old_name rename new_name", allow_mutations="true")
```
See `refactoring-with-squackit` for safety.
