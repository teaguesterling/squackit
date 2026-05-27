# Changelog

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
