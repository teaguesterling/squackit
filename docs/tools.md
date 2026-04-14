# Tools Reference

squackit exposes tools through two sources:

- **Pluckit tools** — CSS selector queries over ASTs (`view`, `find`, `find_names`, `complexity`)
- **Fledgling macros** — SQL-backed tools for file I/O, git, docs, and diagnostics

Pluckit tools take priority when both provide a capability — for example,
pluckit's `find` replaces fledgling's `find_definitions`, `code_structure`,
and `complexity_hotspots`.

Each tool accepts parameters (required as positional args, optional as
`--flags`) and returns markdown by default or JSON with `--json`.

## Pluckit tools

Pluckit tools use [CSS-like selectors](https://github.com/teaguesterling/pluckit)
over ASTs. Selectors include `.fn` (functions), `.class`, `.call`, `#name`
(by name), `[attr]` (by attribute), and combinators like `>`, `+`, `~`.

### view

View source code matching selectors. Returns rendered markdown with file
headings and source blocks.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | string | required | Glob pattern for files |
| `selector` | string | required | CSS selector |

```bash
squackit tool view "src/**/*.py" ".fn#main"
squackit tool view "**/*.py" ".class#AuthService .fn"
```

### find

Find AST nodes matching selectors. Returns a table with file paths, names,
types, and line ranges.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | string | required | Glob pattern for files |
| `selector` | string | required | CSS selector |

```bash
squackit tool find "src/**/*.py" ".fn"
squackit tool find "**/*.py" ".class > .fn"
```

### find_names

Find just the names of AST nodes matching selectors. Lighter than `find`
when you only want names.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | string | required | Glob pattern for files |
| `selector` | string | required | CSS selector |

```bash
squackit tool find_names "src/**/*.py" ".class"
```

### complexity

Find AST nodes ranked by complexity (descendant count).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | string | required | Glob pattern for files |
| `selector` | string | required | CSS selector |

```bash
squackit tool complexity "src/**/*.py" ".fn"
```

### Chain queries (squackit pluck)

For multi-step queries (navigation, filtering, batch operations), use
`squackit pluck` which exposes pluckit's full chain grammar:

```bash
squackit pluck "**/*.py" find .class children .fn count
squackit pluck "**/*.py" find .fn containing "cache" names
```

## File tools

### read_source

Read file lines with optional range, context, and match filtering.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | Path to the file |
| `lines` | string | all | Line range (`"10-20"`) |
| `match` | string | none | Keyword filter |
| `max_lines` | integer | 200 | Truncation limit |

### read_context

Read lines centered around a specific line number.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | Path to the file |
| `center_line` | integer | required | Line to center on |
| `ctx` | integer | 10 | Lines of context above/below |

### list_files

Find files by glob pattern.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pattern` | string | required | Glob pattern |

### project_overview

File counts by language for the project. *No parameters.*

## Documentation tools

### doc_outline

Markdown section outlines with optional keyword/regex search.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_pattern` | string | inferred doc pattern | Glob for markdown files |
| `search` | string | none | Keyword to filter sections |

### read_doc_section

Read a specific markdown section by ID.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | Markdown file path |
| `target_id` | integer | required | Section ID from doc_outline |

## Git tools

### recent_changes

Git commit history.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `n` | integer | 20 | Number of commits |
| `repo` | string | cwd | Repo path |

### file_changes

Files changed between two git revisions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_rev` | string | required | Start revision |
| `to_rev` | string | required | End revision |
| `repo` | string | cwd | Repo path |

### file_diff

Line-level unified diff between revisions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` | string | required | File to diff |
| `from_rev` | string | inferred | Start revision |
| `to_rev` | string | `HEAD` | End revision |

### file_at_version

File content at a specific git revision.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` | string | required | File path |
| `rev` | string | required | Git revision |

### branch_list

List git branches. *No parameters.*

### tag_list

List git tags. *No parameters.*

### working_tree_status

Untracked and modified files. *No parameters.*

### structural_diff

Semantic diff: added/removed/modified definitions between revisions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file` | string | required | File to diff |
| `from_rev` | string | inferred | Start revision |
| `to_rev` | string | `HEAD` | End revision |

### changed_function_summary

Changed functions ranked by complexity between revisions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_rev` | string | required | Start revision |
| `to_rev` | string | required | End revision |

## Conversation tools (MCP only)

These are registered on the MCP server but not exposed via CLI.

- `sessions` — Claude Code conversation sessions
- `messages` — Flattened conversation messages
- `tool_calls` — Tool usage from conversations
- `search_messages` — Full-text search across conversation content

## Diagnostics

### help

Fledgling skill guide. No args for outline, section ID for details.

### dr_fledgling

Runtime diagnostics: version, profile, modules, extensions.

## Compound workflow tools (MCP only)

These compose multiple tools into a single-call briefing. Exposed through
the MCP server; use the CLI tools individually if you want to run them
one at a time.

### explore

First-contact codebase briefing: languages, key definitions, docs, recent
activity.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | string | none | Narrow to a subdirectory |

### investigate

Deep dive on a function or symbol: definition, source, callers, callees.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | string | required | Function or symbol name |
| `file_pattern` | string | inferred | Glob to search within |

### review

Code review prep: changed files, changed functions by complexity, diffs for
top changed files.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_rev` | string | inferred | Start revision |
| `to_rev` | string | `HEAD` | End revision |
| `file_pattern` | string | inferred | Glob pattern |

### search

Multi-source search across definitions, call sites, documentation, and
conversations.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search text |
| `file_pattern` | string | inferred | Glob pattern |
