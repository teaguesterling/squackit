---
name: exploring-unfamiliar-code
description: Use when starting work on a codebase you don't know, or when you need to understand a specific function/module before modifying it. Provides a repeatable drill-in pattern using squackit.
---

# Exploring Unfamiliar Code

## Overview

When you land in an unfamiliar codebase, the temptation is to open files and read. That scales badly. This skill gives you a **drill-in** pattern: start broad, narrow deliberately, stop when you have enough.

**Core principle:** read structured summaries before source. Source is for the last step, not the first.

## Pre-requisite

Squackit's MCP tools must be available. If they're not, this skill doesn't apply — fall back to manual Read/Grep.

## The three phases

### Phase 1: Orient (one tool call)

```
explore()
```

Returns:
- **Languages** — what you're dealing with
- **Key Definitions** — top 20 most complex functions (likely core/tricky)
- **Documentation** — markdown outlines
- **Recent Activity** — last 5 commits

**What to extract:**
- The dominant language (informs CSS selectors)
- 2-3 function names that look central
- Whether there are docs (and where)
- Whether recent commits hint at what the user cares about

Skip this phase if you already know the codebase. Don't skip it on first contact.

### Phase 2: Investigate (one tool call per symbol)

For each interesting function/symbol from Phase 1:

```
investigate(name="<function_name>")
```

Returns:
- **Definition** — file, line range, signature
- **Source** — the function body
- **Called by** — who uses this
- **Calls** — what this depends on

This one tool gives you the definition *and* its neighborhood. Usually enough to decide if this is the right function to focus on.

**When to repeat vs. pivot:**
- If "Called by" reveals a higher-level function you hadn't noticed → investigate that one next
- If the function is trivial → look at its callers, not its source
- If you've seen enough → stop. Don't investigate every function.

### Phase 3: Drill in (targeted queries)

Once you know *which* code matters, use CSS selectors to read exactly what you need:

```
# Read one function
view(source="src/auth.py", selector=".fn#validate_token")

# Read a class with its methods
view(source="src/auth.py", selector=".class#AuthService")

# Read just method names in a class
find_names(source="src/auth.py", selector=".class#AuthService .fn")

# Read a range with surrounding context
read_source(file_path="src/auth.py", lines="10-40", ctx="2")
```

## Decision rules

**When to use `view` vs `read_source`:**
- `view` when you know the symbol (function/class name) — uses AST
- `read_source` when you know the line range or need to search for a keyword

**When to use `find` vs `search`:**
- `find` when you know what kind of thing you're looking for (`.fn`, `.class`, `.call`)
- `search` when you have a term that could appear in code, docs, or conversations

**When to stop:**
- You can answer the user's question → stop
- You've read 3+ functions and still aren't sure → you're drilling too wide; go back to `investigate` with a different name

## Anti-patterns

**Don't list_files + Read everything.**
This is the old way. squackit's tools give you summaries that are 10-100x smaller.

**Don't `view` large selectors like `.fn` without a name.**
`.fn` alone matches every function in the source — you'll get back everything. Always narrow: `.fn#name`, `.class#Name .fn`, or `.fn:has(...)`.

**Don't skip `investigate` and go straight to `view`.**
`view` shows you the function. `investigate` shows you the function *and its context*. Context usually matters more.

## Example: "Help me understand how auth works"

```
explore()
# → Notice "AuthService" and "validate_token" in key definitions

investigate(name="AuthService")
# → Class at src/auth.py, has methods: authenticate, validate_token, _internal_helper
# → Called by: login, middleware
# → Calls: db.get_user, check_password

investigate(name="validate_token")
# → Function at src/auth.py:4, called by authenticate
# → Calls: len (builtin), raise ValueError

view(source="src/auth.py", selector=".class#AuthService .fn#authenticate")
# → Read the specific method implementation
```

Four tool calls. You know the shape of auth in this codebase.

## When to break the pattern

Skip to Phase 3 when:
- The user tells you the file or function to look at
- You're fixing a specific bug with a known location
- You've worked on this codebase before in this session

Use `read_source` as a pure `cat`-replacement when:
- You want line numbers in the output (good for later references)
- You need to grep-filter (use `match` parameter)
- You need to stay in bytes (e.g., checking a regex literal)
