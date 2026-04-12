# Tools Reference

squackit registers fledgling's SQL macros as MCP tools automatically. Each tool
accepts the macro's parameters and returns results as formatted text with
token-aware truncation.

## Code tools

### find_definitions

Find function, class, and module definitions by AST analysis. Use
`name_pattern` with SQL LIKE wildcards (`%`).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_pattern` | string | inferred | Glob pattern for files to search |
| `name_pattern` | string | `%` | SQL LIKE pattern to filter by name |

### find_in_ast

Search code by semantic category: calls, imports, definitions, loops,
conditionals, strings, comments.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_pattern` | string | inferred | Glob pattern for files to search |
| `kind` | string | required | Semantic category to search |
| `name` | string | `%` | Name pattern to filter |

### code_structure

Structural overview with complexity metrics. A good first step for unfamiliar code.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_pattern` | string | inferred | Glob pattern for files to analyze |

### complexity_hotspots

Most complex functions in the codebase, ranked by cyclomatic complexity.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_pattern` | string | inferred | Glob pattern |
| `n` | integer | 20 | Number of results |

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
| `context_lines` | integer | 10 | Lines of context above/below |

### list_files

Find files by glob pattern.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_pattern` | string | inferred | Glob pattern |

### project_overview

File counts by language for the project.

*No parameters.*

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
| `section_id` | integer | required | Section ID from doc_outline |

## Git tools

### recent_changes

Git commit history.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `n` | integer | 20 | Number of commits |

### file_changes

Files changed between two git revisions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_rev` | string | inferred | Start revision |
| `to_rev` | string | `HEAD` | End revision |

### file_diff

Line-level unified diff between revisions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | File to diff |
| `from_rev` | string | inferred | Start revision |
| `to_rev` | string | `HEAD` | End revision |

### file_at_version

File content at a specific git revision.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | File path |
| `rev` | string | `HEAD` | Git revision |

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
| `from_rev` | string | inferred | Start revision |
| `to_rev` | string | `HEAD` | End revision |
| `file_pattern` | string | inferred | Glob pattern |

### changed_function_summary

Changed functions ranked by complexity between revisions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `from_rev` | string | inferred | Start revision |
| `to_rev` | string | `HEAD` | End revision |
| `file_pattern` | string | inferred | Glob pattern |

## Conversation tools

### sessions

Claude Code conversation sessions. *No parameters.*

### messages

Flattened conversation messages.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | string | none | Filter by session |

### tool_calls

Tool usage from conversations. *No parameters.*

### search_messages

Full-text search across conversation content.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Search text |

## Diagnostics

### help

Fledgling skill guide. No args for outline, section ID for details.

### dr_fledgling

Runtime diagnostics: version, profile, modules, extensions.

## Compound workflow tools

These compose multiple tools into a single-call briefing.

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
