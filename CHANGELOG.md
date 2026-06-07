# Changelog

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
