# MCP Resources

Resources are always-available context that agents can read without making a
tool call. They're registered on the MCP server at startup and updated
automatically.

## fledgling://project

**Project overview** — languages, file counts, directory structure.

Returns the output of `project_overview()` plus a top-level directory listing.
Useful for orientation when the agent first connects.

## fledgling://diagnostics

**Runtime diagnostics** — version, profile, loaded modules, DuckDB extensions.

Returns the output of `dr_fledgling()`. Useful for debugging configuration
issues or verifying which fledgling modules are active.

## fledgling://docs

**Documentation outline** — section headings from all markdown files matching
the inferred doc pattern.

Returns `doc_outline()` output. Gives the agent a map of available documentation
without reading full files.

## fledgling://git

**Git status summary** — branches, recent commits, and working tree status
in a single read.

Combines `branch_list()`, `recent_changes(n=10)`, and `working_tree_status()`.

## fledgling://session

**Session summary** — access log for the current MCP session.

Shows which tools have been called, how many times, cache hit rates, and
total latency. Useful for the agent to understand what it has already explored.

!!! note "URI prefix"
    Resource URIs currently use the `fledgling://` scheme for backwards
    compatibility. A future release may migrate to `squackit://`.
