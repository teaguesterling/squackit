---
name: refactoring-with-squackit
description: Use when you need to modify source code via AST operations (rename, replaceWith, wrap, add/remove params) using squackit's pluck tool. Encodes the preview-then-apply safety workflow.
---

# Refactoring with Squackit

## Overview

Squackit's `pluck` MCP tool supports AST-level mutations: rename a function, replace a body, wrap a block, add a parameter. These modify source files on disk — get this wrong and you corrupt the user's code.

**Core principle:** preview every mutation before applying. The mutation safety layer is there because mistakes are easy and irreversible.

## The Iron Law

```
NEVER pass allow_mutations=true without confirmation from the user.
```

Mutations write to disk. If the user didn't explicitly authorize the specific change, block. Don't "helpfully" apply a refactor you thought of on your own.

## The workflow

### Step 1: Preview without mutations

Always start by querying for what you'd match — without mutation ops.

**Scope the source pattern to everywhere the name could appear, not just the file with the definition.** Tests, siblings, and other modules may import or call the symbol. A too-narrow source pattern hides future breakage.

```
# ✅ Broad enough — covers src + tests
pluck(argv="**/*.py find .fn#old_name materialize")

# ❌ Too narrow — misses callers in tests/
pluck(argv="src/auth.py find .fn#old_name materialize")
```

Also preview the call sites and imports separately:

```
pluck(argv="**/*.py find .call#old_name count")
```

And cross-check with grep, because the AST selectors don't match every kind of reference:

```
grep -rn "old_name" --include="*.py"
```

Grep will catch:
- `from foo import old_name` (import statements)
- `"old_name"` in strings (e.g. in `getattr` calls, decorators, error messages)
- `# old_name` in comments (usually safe to ignore)
- Module-qualified refs like `foo.old_name`

**Stop and confirm before proceeding if:**
- The selector matches more nodes than expected
- The selector matches zero nodes (the rename would be a no-op that hides a typo)
- The match spans multiple files and the user only asked about one
- Grep reveals references the AST query missed — you'll need extra steps to cover them

### Step 2: Run with the mutation ops but no `allow_mutations`

```
pluck(argv="src/auth.py find .fn#old_name rename new_name")
```

Without `allow_mutations=true`, squackit returns an error listing the detected mutation ops. This is a **sanity check** — confirms the chain parsed and the detected mutations match what you intended.

Expected response:
```json
{
  "error": "blocked: chain contains mutation operations",
  "mutations": ["rename"],
  "hint": "Set allow_mutations=true to enable...",
  "chain": {...}
}
```

If `mutations` lists ops you didn't intend, your chain is wrong — fix it before applying.

### Step 3: Apply with `allow_mutations=true`

Only when the preview is correct and the user has authorized the change:

```
pluck(argv="src/auth.py find .fn#old_name rename new_name", allow_mutations="true")
```

Expected response:
```json
{
  "chain": {...},
  "type": "mutation",
  "data": {"applied": true}
}
```

### Step 4: Verify

Read the modified file to confirm the change landed as intended:

```
view(source="src/auth.py", selector=".fn#new_name")
```

Or check git status:

```
working_tree_status()
```

## Mutation ops

| Op | Effect | Args |
|---|---|---|
| `rename` | Rename the definition | new_name |
| `replaceWith` | Replace entire node source | code |
| `wrap` | Wrap with before/after text | before, after |
| `unwrap` | Remove outer wrapping, dedent body | — |
| `remove` | Delete the matched nodes | — |
| `append` | Append code to body | code |
| `prepend` | Prepend code to body | code |
| `insertBefore` | Insert before a child anchor | anchor, code |
| `insertAfter` | Insert after a child anchor | anchor, code |
| `addParam` / `removeParam` | Add/remove function parameter | param name |
| `addArg` / `removeArg` | Add/remove call argument | expr / name |

## Patterns

### Rename a function (v1)

`rename` changes the declaration but does NOT update references elsewhere. For a full rename of a cross-module function, plan for **three kinds of references**:

1. **The definition** — `.fn#old_name` matches this
2. **Call sites** — `.call#old_name` matches these
3. **Imports** — `from module import old_name` — NOT matched by pluckit's `.fn` or `.call` selectors as of v0.9.0

Plus potentially:
- **Module-qualified refs** — `module.old_name` (usually matched by `.call`, but not always)
- **String references** — `"old_name"` in decorators, `getattr`, error messages (never matched)

**Recommended workflow:**

```
# Step 1: rename the definition
pluck(argv="**/*.py find .fn#old_name rename new_name",
      allow_mutations="true")

# Step 2: rename call sites (AST-visible)
pluck(argv="**/*.py find .call#old_name rename new_name",
      allow_mutations="true")

# Step 3: update imports and string references with Edit
#   Use grep to find them first:
#     grep -rn "old_name" --include="*.py"
#   Then apply targeted Edits per file.
```

Run tests after step 1 to catch import breakage early. If tests fail with `ImportError`, step 3 is mandatory before proceeding.

**When the `.fn` → `.call` rename is enough:**
- The function is private and local to one file (no imports elsewhere)
- You've verified with grep that no imports exist

**When you'll need more than three steps:**
- The function is referenced by a string name (decorators, `getattr`, pytest fixtures) — add a scripted Edit pass for each
- The function is part of a public API re-exported through `__init__.py` — add the re-export to your plan

### Replace a function body

Replacement text becomes the new node source:

```
pluck(argv="src/api.py find .fn#handler replaceWith 'def handler():\n    return 42'",
      allow_mutations="true")
```

For multi-line replacements, prefer writing the replacement to a file and passing the content as a string. File reference syntax (`@path.py`) is planned but not yet in pluckit as of v0.9.0.

### Wrap with a decorator

```
pluck(argv="src/api.py find .fn#endpoint wrap '@cached' ''",
      allow_mutations="true")
```

### Add a parameter to a function

```
pluck(argv="src/api.py find .fn#handler addParam 'timeout: int = 30'",
      allow_mutations="true")
```

Usually paired with `addArg` at call sites:

```
pluck(argv="src/**/*.py find .call#handler addArg 'timeout=DEFAULT_TIMEOUT'",
      allow_mutations="true")
```

## Anti-patterns

**Don't auto-enable `allow_mutations` based on a general directive.**
User saying "refactor this module" ≠ user authorizing specific AST mutations. Preview first. Confirm the specific changes. Then apply.

**Don't chain a dozen mutations in one call.**
Multi-step mutations are harder to reason about and harder to undo. Prefer several small chains over one big one — you can verify each step.

**Don't assume `rename` handles call sites.**
It doesn't (yet). Two-step it: rename the def, then rename the calls.

**Don't skip the preview step because "it's simple."**
`rename` with a typo in the selector matches nothing — a silent no-op. Without the preview you won't notice your chain didn't do anything until you go looking.

## Reverting a mutation

Pluckit doesn't have an undo. To revert:

1. If uncommitted: `git checkout -- <file>`
2. If committed: `git revert <sha>`

Always verify the change with `file_diff` or Read before committing so you can catch mistakes before they're harder to undo.

## When NOT to use pluck mutations

Sometimes Edit or Write is the right tool:

- **Single-line edits** that don't need AST awareness — use Edit
- **New files** — use Write
- **Config files** (TOML, YAML, JSON) — squackit doesn't parse them; use Edit
- **Complex multi-file transforms** where the AST view is the wrong abstraction — use a scripted Edit loop

Pluck mutations shine for *structural* changes that are awkward with text edits: "rename this class and all its uses," "wrap every handler in a decorator," "add a parameter to every implementation of this method."
