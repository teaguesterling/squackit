# Response-type improvements — surfaced from dogfooding

Empirical findings from an exploration session against `~/Projects/blq` on 2026-06-04. The skill descriptions accurately steered me to the right verbs (`explore` → `find_names` → `investigate` → `find`), but several response-shape issues forced workarounds I wouldn't have needed. Each item below is a discrete change; cherry-pick what's worth doing.

## 1. `explore` — partial failures masquerade as success

**Symptom**

```
### Key Definitions (top 20 by complexity)
(could not load)
```

The overall call returned `{"result": "..."}` — success — but the most useful section silently degraded. No reason given, no signal in the response shape that anything went wrong. A caller programming against this can't distinguish "no definitions" from "extraction failed."

**Proposal**

Either of:

- **(a) Structured result** — switch from one giant markdown string to `{languages: ..., key_definitions: {status, data, reason?}, docs: ..., recent_activity: {status, data, reason?}}`. Each section reports its own status. A failed section still has a `reason` field ("FTS index not populated for /path", "AST extraction unsupported for language X", etc.).
- **(b) Inline error markers** — keep markdown but replace `(could not load)` with `(error: FTS index not populated — run \`fts_stats()\` to check, then rebuild)`. Same string format, just useful enough to act on.

(a) is the bigger improvement but (b) is one-line. Maybe both: (a) for the API, (b) as a fallback for the rendered output.

## 2. `explore` — `recent_activity` ignores the `path` argument

**Symptom**

```python
explore(path="/home/teague/Projects/blq")
# Languages, Documentation sections correctly reflect /Projects/blq
# Recent Activity shows commits from /home/teague/.dotfiles (session cwd)
```

The git-log subquery in `recent_activity` runs against cwd, not against the requested `path`. Language scan and doc scan both honor `path`; only this one section leaks.

**Proposal**

Pipe `path` through to the git-context resolver in `explore`'s `recent_activity` builder, same way it reaches `project_overview`'s language scan. If `path` isn't a git repo, return an empty `recent_activity` with `reason="not a git repository"` rather than silently falling back to cwd.

## 3. `investigate` — Source section truncates without signaling

**Symptom**

```
### Definition
| ... | start_line | end_line | ... |
| ... | 187        | 242      | ... |

### Source
 187  def _apply_mcp_thread_limits() -> None:
 ...
 236          ThreadPoolExecutor(max_workers=async_workers, ...),
```

Definition says the function ends at line 242. Source stops at 236. No "...truncated" footer, no `max_lines` parameter in the call to bump. The caller has to notice the line-number mismatch to know there's missing source.

**Proposal**

Either:

- Always render Source through line `end_line` (the def is bounded; serving the full body is the point of `investigate`).
- OR add a `max_source_lines` parameter (default high enough to fit most functions) plus a footer `[truncated — N more lines; fetch with read_source(file_path, lines="237-242")]` when capped.

## 4. Selectors match call names, not qualified attribute paths

**Symptom**

```python
find(source="/blq/**/*.py", selector=".call#connect")
# Returns 28 rows: 21 duckdb.connect(...), 4 db.connect(), 3 bare connect()
```

`.call#connect` matches any call whose attribute name is `connect`, regardless of receiver. To ask "every call to `duckdb.connect`", I had to inspect `peek` post-hoc. This is a real expressiveness gap — call-pattern selectors are one of the most useful queries and they conflate receiver-disambiguation.

**Proposal**

Either of:

- **Qualified selector syntax** — `.call#duckdb.connect` matches by full attribute path. `.call#*.connect` matches any receiver. Plain `.call#connect` keeps current semantics for backward compat.
- **Receiver in result columns** — add `receiver` (e.g., `"duckdb"`, `"db"`, `None` for bare) as a top-level column. Callers filter post-hoc but at least can.

Selector syntax is more powerful; result columns are easier to ship.

## 5. `find` returns ~15 columns; ~4 are useful

**Symptom**

A `find` row currently includes: `node_id, type, semantic_type, flags, name, qualified_name, signature_type, parameters, modifiers, annotations, file_path, language, start_line, end_line, parent_id, depth, sibling_index, children_count, descendant_count, scope, peek`.

For 99% of caller intents, only `file_path`, `start_line`, `end_line`, `name`, and `peek` matter. The rest is internal AST bookkeeping that bloats responses (and Claude's context window).

**Proposal**

Default to a compact column set — `file_path | start_line | end_line | name | peek`. Add `verbose=True` for the current full set when the caller actually needs it (e.g., debugging AST structure).

This is also the cheapest improvement on the list — table-projection at the response layer, no logic changes.

## 6. Consistent shape across verbs

`explore` returns markdown with sections. `find` returns a markdown table. `investigate` returns markdown with sub-headings and embedded tables. Each is sensible alone but reading three in one session means three different parse strategies.

**Proposal**

Either fully commit to markdown (with consistent section-header conventions across verbs) or move to JSON+embedded-markdown. The current mix forces callers (human or agent) to context-switch.

## 7. Truncation signaling

`explore`'s doc table did this correctly: `--- omitted 1283 of 1293 rows ---`. But `find` and `investigate` don't always indicate when results are capped at `max_results`/`max_lines`. A caller seeing 50 rows can't tell whether 50 is the universe or just the first page.

**Proposal**

Standardize a footer like `[showing N of M; pass max_results=K to widen]` on every verb that has a default cap.

## Priority suggestion

If you only do two of these:

1. **#5 (compact columns)** — biggest reduction in noise across every `find`/`find_names` call.
2. **#2 (recent_activity path leak)** — cleanest correctness bug; one-liner fix.

If three: add **#3 (investigate source truncation)** — that one bit me directly and the "Definition end_line vs Source last line" mismatch is unambiguous.

The selector-qualification work (#4) is the most expressive improvement but also the most design. Worth its own thread.
