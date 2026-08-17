# Changelog

## 0.8.3

Three fixes with one theme: a failure must not be representable as an ordinary
result. Nothing here changes what a working call returns.

### Fixed — `investigate` reported failed lookups as confirmed absences (#14)

Every exception from the definition query was caught and rendered with the
sentence used for a genuine miss:

    No definition found for 'X'. Try a broader pattern or check spelling.

So a permission error, a binder error and "that symbol isn't here" were
indistinguishable, and the advice actively misdirected — the pattern was never
the problem. This is how the 0.8.1 sandbox bug presented: every symbol in a
healthy project reported missing, for hours, while the server called all its
tools healthy.

A failed lookup now says so, names the underlying error, and reports the
pattern it searched. The friendly wording is kept for the genuine empty case,
where it is good advice.

### Fixed — a raising pluckin lost its tools silently (#14)

`collect_pluckin_tools` swallowed per-pluckin exceptions with a bare `pass`,
under a comment claiming the error would be "surfaced contextually". Nothing
surfaced it. The guard is right — one broken pluckin must not take down the
registry — but it now logs a warning naming the pluckin and the error.

Not reachable today (no shipped pluckin defines `squackit_tools`), fixed as
latent. The symptom it would produce — a silently shorter tool surface — was
independently hit through another mechanism and cost a four-combination version
bisection, because a shorter tool list doesn't read as a failure. It reads as a
different, reasonable version of the product.

### Fixed — `ast_replace` / `ast_patch` read as mutating and are not (#16)

Connection macros are published with a description generated from the
signature, so these carried no semantics at all:

    Query: ast_replace(source, selector, new_text, language)

These are sitting_duck SQL macros. A SQL macro cannot write files — it computes
the patched source and returns it, which is coherent, and sitting_duck is not
misbehaving. But over MCP the caller reads a verb. One did: it called
`ast_replace` to repair a bug, got a successful-looking table back, and changed
nothing on disk.

Generated descriptions for macros whose *name* implies an effect now state that
they return the patched result and modify nothing. Read-only macros are
unchanged — a disclaimer on all ninety is context every agent pays for.

For an actually-mutating primitive, see #17.

### Fixed — `__version__` was four releases stale (#15, #2)

`squackit.__version__` was a hand-written `"0.4.1"` against a distribution
version of `0.8.2`, and survived `--force-reinstall` because it derived from
nothing. It is now read from `importlib.metadata`, and the smoke test asserts
that correspondence rather than a literal — which is what let both drift in
agreement with each other and with nothing else.

## 0.8.2

### Fixed — AST tools could not read a source outside the working directory

`find` / `view` / `find_names` / `complexity` build their own connection with
no root, so fledgling's sandbox confined them to the process working
directory. An absolute source anywhere else — `find(source="/srv/code/x/**/*.py")`
— raised a permission error. The connection is now rooted at the source's own
directory, which is the scope the caller named. Relative sources are untouched:
they already resolve against the working directory, and re-rooting them would
double-prefix the path.

Each rooted plucker gets its own AST cache file, keyed by root. DuckDB's
filesystem allow-list belongs to the database *instance*, not the connection,
and every connection to one file shares an instance — so a single shared cache
meant the first lockdown won for the life of the process and later roots were
silently ignored. The cache lives in the temp directory rather than inside the
root, since a served corpus is mounted read-only.

### Fixed — de-vendoring aborted the transaction and blamed the next query

When a glob's tree had no `.git`/`.gitmodules` ancestor, the walk up degraded
to `/` and `_submodule_prefixes('')` read the filesystem root — refused under
the sandbox. The failure was swallowed by design (de-vendoring is an
optimization, not a correctness gate), but the aborted DuckDB transaction was
not rolled back, so the *next* statement failed with "Current transaction is
aborted" — pointing at the AST cache, which had done nothing wrong. Submodule
exclusion is now skipped when there is no repository to read, and the fallback
rolls back so the connection stays usable.

### Fixed — `read_source` output was double-spaced

Rows carry each line's own trailing newline, and the text renderer joined them
with another, so every second line was blank. That also broke head/tail
truncation, whose omission message is inserted by row index.

## 0.8.1

### Fixed — every code query returned "not found" under fledgling >= 0.13

fledgling 0.13 added `sandbox: bool = True` to `connect()`, restricting the
connection's filesystem allow-list to the project root. squackit's inferred
default patterns were relative (`**/*.py`), and DuckDB resolves a relative
glob against the process working directory — not against the root. A server's
cwd is never the corpus it serves, so the glob landed outside the allow-list
and the query raised:

    Permission Error: Cannot access file "**/*.py"
                      - file system operations are disabled by configuration

`investigate` catches query failures and reports them as a miss, so the
visible symptom was:

    No definition found for 'parse_config'. Try a broader pattern or check spelling.

for every symbol, in a project where those symbols existed — while the server
reported all of its tools healthy. A missing-result message is
indistinguishable from an empty corpus, which is what made this quiet.

Patterns are now anchored at the project root wherever they reach DuckDB:

- `ProjectDefaults` carries `root` and exposes `code_glob` / `doc_glob`;
  `TOOL_DEFAULTS` names those rather than the raw pattern fields.
- `scoped_code_pattern` / `scoped_doc_pattern` anchor their results.
- Caller-supplied *relative* patterns are anchored too, so `docs/**/*.md`
  means "docs in this project" rather than a permission error.
- Absolute patterns are passed through untouched.

The raw `code_pattern` / `doc_pattern` fields stay relative — `prompts.py`
shows them to users, where an absolute corpus path is noise.

### Changed — unscoped `investigate` falls back to the served root, not cwd

`resolve_scope_path` gained a `default` argument, giving the chain
`explicit path -> runtime.active_root -> served project root -> cwd`.
Previously an unscoped call scoped to the process working directory, which
was a workable stand-in only when the tool ran from inside the repo. For a
served corpus it searched an unrelated directory, and under the sandbox it
failed outright. Cross-project isolation is unchanged: results still come
from one project, now named explicitly instead of inferred from cwd.

### Changed — dependency bounds relaxed to `<1.0`

The `fledgling-mcp>=0.12,<0.13` bound excluded 0.13.1, which is where
fledgling relaxed its own exact `duckdb==1.5.2` pin to a range. Against a
`duckdb==1.5.5` requirement pip did not report a conflict — it backtracked
to squackit 0.7.0 and installed that, reporting success while shipping code
two releases old.

## 0.8.0

### Added — source text from `find`, and a cache instead of re-parsing
`find` returns source text via a caller-chosen peek extent, and the AST cache
is enabled so repeated calls query a materialized table rather than re-parsing
the tree every time. Selection is delegated to sitting_duck's `ast_select`
rather than reimplemented here.

Cached tables now also carry `start_column` / `end_column`. These were not
zeroed before — they were *absent*, since `read_ast` only adds them under
`source := 'full'`. On minified input every node reports `start_line = 1`, so
character offsets are the only way to isolate a node: peek says how much text a
node carries, the columns say where it is.

### Fixed — `investigate` preferred substrings over exact names
`investigate(name)` resolved definitions with a LIKE substring
(`name_pattern='%name%'`), so a deep-dive on `ensure_loaded` dragged in
`_ensure_loaded` — including vendored copies under `.venv`. Because the Source
and Calls sections key off `defs[0]`, the briefing could describe the **wrong
function** entirely. Exact matches now win.

### Changed — requires `ast-pluckit>=0.15,<0.16`
This package calls `Plucker(..., cache=True, peek=...)`. That keyword arrived in
pluckit 0.15.0; the 0.14.0 the previous constraint allowed does not have it, so
a normal install resolved a pluckit whose every tool call raised `TypeError`.
The suite had hidden this by running with `PYTHONPATH` pointed at a checkout;
it is now verified against the published wheel.

### Fixed — tests that need a fledgling checkout now skip
Six tests read repo-shaped content (a `docs/` tree, `fledgling/pro/__main__.py`)
that only a fledgling source checkout has. Under the installed-package layout
they failed on assertions about *content* — reading as bugs in squackit's own
defaults inference — instead of saying what was missing. They now skip, naming
`FLEDGLING_REPO_PATH`.

## 0.7.1

### Added — server consumes default-limit knobs
`config()`'s `max_results_default` / `complexity_max_results_default` session
knobs are now honored by the server's tool truncation, so the in-memory limits
set via `config()` actually take effect.

### Changed — ast-pluckit 0.14 selector delegation
Consume ast-pluckit 0.14.0, which delegates CSS-selector matching to
sitting_duck's `ast_select` (fixes `:has(.call#name)` over-match, sitting_duck
#72 / squackit #8); pinned `ast-pluckit>=0.14,<0.15` with a regression test.

### Added — AST tools de-vendor the source glob (fledgling #47)
`find` / `find_names` / `view` / `complexity` now exclude submodule, build,
cache, and checked-in third-party trees from a whole-repo glob, so they focus on
the project's own code instead of drowning in vendored deps. On a DuckDB
extension with `duckdb/` + `rdkit/` git submodules, `find_names('**/*.cpp', '.function')`
went from **35k+ names parsed in ~9 s to 164 in ~2 s** (~660× less work at the
parse layer).

- Reuses fledgling's single-source-of-truth ignore policy (`_is_vendored_path`
  denylist + `_submodule_prefixes` git-awareness, new in fledgling 0.12) — the
  filtered file set is handed to sitting_duck as an explicit `read_ast` list,
  which parses identically to a glob (verified same results), so only *which*
  files are parsed changes, not how selectors match.
- The repo root for submodule exclusion is derived from the **source glob**
  (walking up to the nearest `.gitmodules`/`.git`), not the server's cwd, so it
  works when an agent queries a different project by absolute path.
- Explicit targets are honored: a single-file source, a DuckDB table name, or a
  glob aimed *into* a vendored/submodule tree (e.g. `rdkit/**/*.cpp`) is passed
  through unfiltered rather than filtered to zero.

### Changed
- Require `fledgling-mcp>=0.12` for the `_is_vendored_path` / `_submodule_prefixes`
  ignore-policy macros.

## 0.6.0

### Added — `investigate(path=)` for cross-project scoping
`investigate(name, path=)` accepts an explicit `path` argument and scopes the
symbol-lookup to that path's `scoped_code_pattern`. Without `path=`, defaults
to the process `cwd`-scoped pattern (was: the global registry pattern, which
substring-matched across every indexed project — e.g. `investigate("main")`
returned hits from vendored JS in unrelated repos). Pre-existing
`file_pattern=` overrides still work.

### Added — per-root FTS search
`search_*` tools now accept `root=<dir>` to index + search any repo on the
fly. Indexes are LRU-cached per root for the session, so repeated queries
in the same root stay cheap.

### Fixed — agent-ergonomics findings
- FTS now fails loud on index errors instead of silently returning empty.
- `investigate` no longer mislabels callers in cross-file results.
- Selector docs verified end-to-end against the running tool surface.
- `lackpy` 0.12 dropped top-level re-exports; switched to submodule imports
  to keep import-time light.

### Docs
- `:has(.call#NAME)` works now that pluckit delegates selector compilation
  to sitting_duck (was a notable known-bug in 0.5.0).
- Tool count corrected in README (~20 was wrong; actually ~35 / ~40 full).
- Receiver-qualified call selectors (#4) marked DONE.
- Response-type improvement proposals collected in `docs/proposals/`.

## 0.5.0

### Changed — migrate off pluckit/fledgling private internals
squackit no longer reaches into private connection attributes; it now uses the
public, SemVer'd contract from fledgling 0.10 and pluckit 0.13:

- `con._con` → `con.con`; `con._tools` → `con.tools` (`server.py`, `cli.py`).
- The lazy FTS rebuild (which poked `con._con` + a private `_fts_built` flag)
  now delegates to fledgling's `Connection.ensure_fts()`. squackit keeps only
  the `_FTS_MACROS` gating (which tools need FTS).
- `plucker._registry.pluckins` → `plucker.pluckins`; `Chain._MUTATION_OPS`
  → `Chain.MUTATION_OPS` (`tools.py`).

### Dependencies — declare what we actually use, with compatible ranges
- `ast-pluckit>=0.13.0,<0.14` (was `>=0.9.0`) — needs the public `pluckins`
  accessor + `pluckins.search`/`viewer`.
- `fledgling-mcp>=0.10.0,<0.11` — **newly declared.** squackit imports
  `fledgling.tools.ToolInfo` and needs the `Connection.con/.tools/.ensure_fts`
  contract; declaring it makes `Plucker.connection` always a `fledgling.Connection`
  (ending the bare-duckdb surprise that caused the `'_con' missing` failures).

### Net
The brittle, undocumented, conditionally-present coupling is gone: a grep for
private reach-ins (`con._con`, `con._tools`, `_registry`, `_MUTATION_OPS`,
`_fts_built`) returns zero. The suite now composes by a versioned public API.
