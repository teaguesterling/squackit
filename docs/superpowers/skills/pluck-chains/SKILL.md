---
name: pluck-chains
description: Use when you need to compose multi-step AST queries with squackit — filtering, navigating between AST nodes, or batching queries. Prefer single-purpose tools (view, find, find_names) for simple cases.
---

# Pluck Chains

## Overview

The `pluck` MCP tool accepts pluckit's chain grammar — a pipeline of operations over AST nodes. Use it when the single-purpose tools (`view`, `find`, `find_names`, `complexity`) aren't enough: multi-step queries, navigation, filtering, batch operations.

**Core principle:** pluck is a DSL, not a shell command. Each token is either a source pattern, an op, or an op's argument. Think Unix pipes with AST semantics.

## When to reach for pluck

Use `pluck` when you need to:
- Chain multiple filter steps (`find .fn containing cache not_ at_line 50`)
- Navigate between related nodes (`find .class children`)
- Run multiple queries against the same source (`find .fn names reset find .class names`)
- Apply mutations (`find .fn#old rename new` — requires `allow_mutations=true`)

Use `view`/`find`/`find_names`/`complexity` instead when:
- One find + one terminal is enough
- You want typed structured output (find returns a table, pluck returns JSON)
- Simpler is better

## Grammar

```
<source_pattern> [op [arg]...]... [terminal]
```

- **Source pattern** — first positional arg (glob or file path)
- **Ops** — method names that transform a Selection
- **Terminals** — produce a final result

Optional prefix flags: `--plugin <Name>` (load a pluckit plugin like `AstViewer`), `--repo <path>` (git repo for history ops).

## Op categories

### Query ops (return a new Selection)
| Op | Effect | Example |
|---|---|---|
| `find <sel>` | Find nodes matching selector | `find .fn` |
| `filter <kw=val>` | Keyword filter | `filter name=foo` |
| `filter_sql <where>` | Raw SQL WHERE clause | `filter_sql "start_line>10"` |
| `not_ <sel>` | Exclude matches | `not_ .fn#test_*` |
| `unique` | Deduplicate | `unique` |

### Navigation ops
| Op | Effect |
|---|---|
| `parent` | Immediate parent nodes |
| `children` | Direct children |
| `siblings` | Same-parent siblings |
| `ancestor <sel>` | Nearest matching ancestor |
| `next` / `prev` | Next/prev sibling |

### Address ops
| Op | Effect |
|---|---|
| `containing <text>` | Filter to nodes whose source contains text |
| `at_line <n>` | Nodes that span line n |
| `at_lines <s> <e>` | Nodes overlapping the range |

### Terminals (produce a result)
| Terminal | Returns |
|---|---|
| `names` | List of names |
| `count` | Scalar count |
| `text` | List of source strings |
| `attr <name>` | List of one attribute |
| `complexity` | List of per-node complexity |
| `materialize` | Full metadata dict per node |
| `view` | Rendered markdown (requires `--plugin AstViewer`) |

### Control
- `reset` — clear selection, start fresh from source
- `pop` — return to previous find's selection

### Mutations (require `allow_mutations=true`)
See `refactoring-with-squackit`.

## Patterns

### Single-step chain
```
pluck(argv="**/*.py find .fn count")
# → all function count across the codebase
```

### Filtered chain
```
pluck(argv="**/*.py find .fn containing 'TODO' names")
# → names of functions with "TODO" in their body
```

### Navigation chain
```
pluck(argv="src/auth.py find .class#AuthService children find .fn names")
# → names of methods directly inside AuthService
```

Note: `children` returns all child AST nodes (docstrings, decorators, assignments, etc.), not just functions. Follow `children` with `find .fn` to isolate methods.

### Batch queries with `reset`
```
pluck(argv="**/*.py find .fn names reset find .class names")
# → the final terminal wins — both runs against the same source
```

Note: `reset` clears the selection and any following `find` starts fresh from the source. If you want results from both queries, make two separate `pluck` calls — `reset` overwrites the prior result.

### View terminal (rendered source)
```
pluck(argv="--plugin AstViewer src/auth.py find .fn#validate_token view")
# → markdown with file heading + code block
```

`view` requires the `AstViewer` pluckin explicitly via `--plugin AstViewer`.

## Selector cheat sheet

Same CSS grammar as the single-purpose tools:

- `.fn` / `.class` / `.call` — by kind
- `#name` — by exact name (e.g. `.fn#main`)
- `[attr]` — by attribute (e.g. `.fn[name*="test"]`)
- `.class > .fn` — direct children
- `.fn:has(.call#foo)` — functions that call foo
- `.class[name*="Test"]` — classes with "Test" in name

Escape whitespace in args with quotes: `containing "return None"`.

## Debugging chains

If a chain returns `(no results)` or errors:

1. **Narrow the source** — start with a single file: `src/auth.py` instead of `**/*.py`
2. **Check the selector** — run `find <sel>` alone first to see if it matches anything
3. **Use `materialize`** — returns all node metadata, useful for inspecting what you actually have
4. **Check required plugins** — `view` needs `--plugin AstViewer`, `history` needs `--plugin History`
5. **`ModuleNotFoundError` or `ImportError`** — the MCP server's pluckit install is stale or broken. This is not a chain syntax issue — stop iterating and report it. The server process needs to be restarted after `pip install --upgrade ast-pluckit`. No chain variation will fix an import error.

## Anti-patterns

**Don't rebuild what the single-purpose tools already do.**
```
❌ pluck(argv="**/*.py find .fn names")
✅ find_names(source="**/*.py", selector=".fn")
```
Same result, clearer intent. Reach for `pluck` when you need ops the single-purpose tools don't expose.

**Don't chain unnecessary steps.**
```
❌ pluck(argv="**/*.py find .fn unique count")  # unique is redundant
✅ pluck(argv="**/*.py find .fn count")
```

**Don't forget terminals.**
A chain without a terminal defaults to `materialize`, which is verbose. Always end with the terminal that matches your intent.

## Output shape

`pluck` returns a JSON string with three fields:

```json
{
  "chain": {...},   // The parsed chain (source + steps)
  "type": "names",  // Which terminal ran
  "data": [...]     // The terminal's output
}
```

Agents should parse the `data` field based on `type`. Don't pattern-match on the whole JSON — the `type` tells you how to read `data`.
