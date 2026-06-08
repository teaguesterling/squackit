"""Fledgling: FastMCP server wrapping fledgling's SQL macros.

Auto-generates MCP tools from every fledgling table macro. Each tool
accepts the macro's parameters and returns results as formatted text.

Usage::

    # As a module
    python -m squackit.server

    # Programmatic
    from squackit.server import create_server
    mcp = create_server()
    mcp.run()

    # With custom config
    mcp = create_server(root="/path/to/project", modules=["source", "code"])
    mcp.run()
"""

from __future__ import annotations

import inspect
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from pluckit import Plucker
from squackit.defaults import (
    ProjectDefaults, apply_defaults, infer_defaults, load_config,
)
import time as _time

from squackit.formatting import (
    _format_markdown_table,
    _truncate_rows,
    _HEAD_TAIL,
)
from squackit.prompts import register_prompts
from squackit.session import AccessLog, SessionCache
from squackit.tool_config import ToolPresentation, build_tool_registry
from squackit.workflows import register_workflows



def create_server(
    name: str = "squackit",
    root: Optional[str] = None,
    init: Optional[str | bool] = None,
    modules: Optional[list[str]] = None,
    profile: str = "analyst",
) -> FastMCP:
    """Create a FastMCP server with fledgling tools.

    Args:
        name: Server name.
        root: Project root. Defaults to CWD.
        init: Init file path, False for sources, None for auto-discover.
        modules: SQL modules to load (when using sources).
        profile: Security profile.

    Returns:
        A FastMCP server instance ready to .run().
    """
    from fastmcp import FastMCP
    from pluckit.pluckins.search import Search
    from pluckit.pluckins.viewer import AstViewer

    plucker = Plucker(
        repo=root, profile=profile, modules=modules, init=init,
        plugins=[AstViewer, Search],
    )
    con = plucker.connection
    mcp = FastMCP(name)

    # Infer smart defaults, merge with config file overrides
    project_root = Path(root) if root else Path.cwd()
    overrides = load_config(project_root)
    defaults = infer_defaults(con, overrides=overrides, root=project_root)
    mcp._defaults = defaults

    cache = SessionCache()
    access_log = AccessLog(con.con)
    mcp.session_cache = cache
    mcp.access_log = access_log

    # Register each macro as an MCP tool
    from squackit.tools import PLUCKIT_TOOLS, collect_pluckin_tools
    extra = list(PLUCKIT_TOOLS) + collect_pluckin_tools(plucker)
    registry = build_tool_registry(con.tools, extra_tools=extra)
    for presentation in registry.values():
        _register_tool(mcp, con, presentation, defaults, cache, access_log)

    # ── MCP Resources ───────────────────────────────────────────────
    # Static/slow-changing context available without tool calls.

    @mcp.resource("fledgling://project",
                  name="project",
                  description="Project overview — languages, file counts, directory structure.")
    def project_resource() -> str:
        sections = []

        overview = con.project_overview()
        sections.append("## Languages\n")
        sections.append(_format_markdown_table(overview.columns, overview.fetchall()))

        top_level = con.list_files("*")
        sections.append("\n## Top-Level Files\n")
        sections.append(_format_markdown_table(top_level.columns, top_level.fetchall()))

        return "\n".join(sections)

    @mcp.resource("fledgling://diagnostics",
                  name="diagnostics",
                  description="Fledgling version, profile, loaded modules, extensions.")
    def diagnostics_resource() -> str:
        diag = con.dr_fledgling()
        return _format_markdown_table(diag.columns, diag.fetchall())

    @mcp.resource("fledgling://docs",
                  name="docs",
                  description="Documentation outline — all markdown files with section headings.")
    def docs_resource() -> str:
        outline = con.doc_outline("**/*.md")
        return _format_markdown_table(outline.columns, outline.fetchall())

    @mcp.resource("fledgling://git",
                  name="git",
                  description="Current branch, recent commits, and working tree status.")
    def git_resource() -> str:
        sections = []

        branches = con.branch_list()
        sections.append("## Branches\n")
        sections.append(_format_markdown_table(branches.columns, branches.fetchall()))

        commits = con.recent_changes(5)
        sections.append("\n## Recent Commits\n")
        sections.append(_format_markdown_table(commits.columns, commits.fetchall()))

        status = con.working_tree_status()
        status_cols = status.columns
        status_rows = status.fetchall()
        sections.append("\n## Working Tree Status\n")
        if status_rows:
            sections.append(_format_markdown_table(status_cols, status_rows))
        else:
            sections.append("Clean working tree.")

        return "\n".join(sections)

    @mcp.resource("fledgling://session",
                  name="session",
                  description="Session access log — tool call history, cache stats.")
    def session_resource() -> str:
        summary = access_log.summary()
        total = summary["total_calls"]
        cached = summary["cached_calls"]
        pct = int(100 * cached / total) if total > 0 else 0
        entries = cache.entry_count()

        sections = []
        sections.append(
            f"Session: {total} tool calls, {cached} cached ({pct}%)\n"
            f"Cache: {entries} entries"
        )

        # Recent calls table
        recent = access_log.recent_calls(20)

        if recent:
            sections.append("\n## Recent Calls\n")
            cols = ["#", "tool", "args", "rows", "cached", "ms"]
            rows = []
            for r in recent:
                args_str = str(r[2])
                if len(args_str) > 60:
                    args_str = args_str[:57] + "..."
                rows.append((
                    r[0], r[1], args_str, r[3],
                    "yes" if r[4] else "no",
                    f"{r[5]:.0f}",
                ))
            sections.append(_format_markdown_table(cols, rows))

        return "\n".join(sections)

    # Register compound workflow tools
    register_workflows(mcp, con, defaults)

    # Register MCP prompt templates
    register_prompts(mcp, con, defaults)

    return mcp


def _register_executor_tool(mcp, presentation: ToolPresentation):
    """Register an executor-based tool (e.g. pluckit) as an MCP tool."""
    tool_name = presentation.name
    params = presentation.params
    description = presentation.description
    is_text = presentation.format == "text"
    executor = presentation.executor

    # Truncation defaults from presentation
    if presentation.max_lines is not None:
        limit_param = "max_lines"
        default_limit = presentation.max_lines
    elif presentation.max_rows is not None:
        limit_param = "max_results"
        default_limit = presentation.max_rows
    else:
        limit_param = None
        default_limit = 0

    async def tool_fn(**kwargs) -> str:
        # Pop limit param before passing to executor — it's a presentation
        # concern, not an executor input.
        max_limit = default_limit
        if limit_param and limit_param in kwargs:
            val = kwargs.pop(limit_param)
            if val is not None:
                try:
                    max_limit = int(val)
                except (TypeError, ValueError):
                    pass
            else:
                # Caller passed limit=None — fall back to runtime config.
                # `complexity` is its own bucket; everything else uses the
                # general default_max_results.
                from squackit.runtime import get_runtime
                rt = get_runtime()
                if tool_name == "complexity":
                    max_limit = rt.complexity_max_results_default
                elif limit_param == "max_results":
                    max_limit = rt.max_results_default

        # Pop verbose param the same way — opts out of compact_columns
        # projection so the caller can see the full AST bookkeeping schema.
        verbose = False
        if "verbose" in kwargs:
            v = kwargs.pop("verbose")
            if isinstance(v, str):
                verbose = v.lower() in ("true", "1", "yes")
            elif v is not None:
                verbose = bool(v)

        filtered = {k: v for k, v in kwargs.items() if v is not None}

        try:
            result = executor(**filtered)
        except Exception as e:
            etype = type(e).__name__
            if etype == "PluckerError":
                return f"Error: {e}"
            raise

        # View -> markdown (truncate by blocks if too many)
        if hasattr(result, 'markdown') and hasattr(result, 'blocks'):
            blocks = result.blocks
            if max_limit > 0 and len(blocks) > max_limit:
                kept = blocks[:max_limit]
                omitted = len(blocks) - max_limit
                body = "\n\n".join(b.markdown for b in kept if b.markdown)
                return body + f"\n\n--- omitted {omitted} of {len(blocks)} blocks ---"
            return result.markdown or "(no results)"
        # DuckDB relation -> table (truncate rows)
        if hasattr(result, 'columns') and hasattr(result, 'fetchall'):
            cols = result.columns
            rows = result.fetchall()
            if not rows:
                return "(no results)"
            omission = None
            if max_limit > 0 and len(rows) > max_limit:
                omitted = len(rows) - max_limit
                rows = rows[:max_limit]
                omission = f"--- omitted {omitted} rows ---"

            # Project to compact_columns by default. Tools opt in by setting
            # presentation.compact_columns; callers opt OUT per-call with
            # verbose=true. Unknown column names in compact_columns are
            # silently skipped so a schema change doesn't break the projection.
            if presentation.compact_columns and not verbose:
                keep_idx = [
                    i for i, name in enumerate(cols)
                    if name in presentation.compact_columns
                ]
                # Reorder to match compact_columns order rather than source order.
                order = {name: pos for pos, name in enumerate(presentation.compact_columns)}
                keep_idx.sort(key=lambda i: order.get(cols[i], len(order)))
                if keep_idx:
                    cols = [cols[i] for i in keep_idx]
                    rows = [tuple(row[i] for i in keep_idx) for row in rows]

            if is_text:
                lines = []
                for row in rows:
                    parts = [str(v) for v in row if v is not None]
                    lines.append("  ".join(parts))
                if omission:
                    lines.append(omission)
                return "\n".join(lines)
            text = _format_markdown_table(cols, rows)
            if omission:
                text += "\n" + omission
            return text
        # list -> joined (truncate)
        if isinstance(result, list):
            if not result:
                return "(no results)"
            if max_limit > 0 and len(result) > max_limit:
                omitted = len(result) - max_limit
                kept = result[:max_limit]
                return "\n".join(str(item) for item in kept) + \
                       f"\n--- omitted {omitted} of {len(result)} items ---"
            return "\n".join(str(item) for item in result)
        return str(result) if result else "(no results)"

    tool_fn.__name__ = tool_name
    tool_fn.__qualname__ = tool_name
    tool_fn.__doc__ = description

    required_set = set(presentation.required)
    annotations = {}
    sig_params = []
    for p in params:
        if p in required_set:
            annotations[p] = str
            sig_params.append(inspect.Parameter(
                p, inspect.Parameter.KEYWORD_ONLY, annotation=str,
            ))
        else:
            annotations[p] = Optional[str]
            sig_params.append(inspect.Parameter(
                p, inspect.Parameter.KEYWORD_ONLY,
                default=None, annotation=Optional[str],
            ))
    if limit_param:
        annotations[limit_param] = Optional[int]
        sig_params.append(inspect.Parameter(
            limit_param, inspect.Parameter.KEYWORD_ONLY,
            default=None, annotation=Optional[int],
        ))
    if presentation.compact_columns:
        # Expose `verbose` so MCP clients can request the full AST schema.
        annotations["verbose"] = Optional[bool]
        sig_params.append(inspect.Parameter(
            "verbose", inspect.Parameter.KEYWORD_ONLY,
            default=None, annotation=Optional[bool],
        ))
    tool_fn.__annotations__ = {**annotations, "return": str}
    tool_fn.__signature__ = inspect.Signature(
        sig_params, return_annotation=str,
    )

    mcp.add_tool(tool_fn)


# FTS search macros need a one-time index build. The index lives in the
# (in-memory) connection and rebuild is manual + ~2s, so build it lazily on
# first search rather than taxing every server startup.
_FTS_MACROS = {"search_code", "search_content", "search_docs"}


def _ensure_fts(con):
    """Build the FTS index once, lazily on first FTS search. fledgling owns the
    build + idempotency (Connection.ensure_fts); squackit only decides *which*
    tools need it (see _FTS_MACROS)."""
    con.ensure_fts()


# ── Per-root FTS index cache (opt-in) ──────────────────────────────────────
# An FTS macro (search_*) queries a BM25 index built into ONE connection — the server's
# project. To let an agent full-text-search a *different* repository, an FTS tool accepts a
# `root`: we build & cache a small connection-per-root and run the macro there. This is
# opt-in — without `root`, FTS searches the server's project exactly as before.
#
# Safety: `root` is validated to an existing directory (no globs, no files); the build is
# scoped to that root (Plucker derives its own globs); the cache is LRU-bounded so a session
# can't accumulate unbounded connections. squackit's structural tools already read arbitrary
# paths, so this adds no new filesystem exposure — and it deliberately does NOT reach into
# fledgling's private sandbox helpers (keeping the public-contract boundary intact).
_FTS_CACHE_MAX = 4
_fts_lock = threading.Lock()


def _resolve_fts_root(root: str) -> Path:
    """Validate an FTS ``root`` → an existing directory (absolute). Rejects globs and
    non-directories so a stray ``source``-style glob or a file path can't trigger a build.
    Raises ValueError with an agent-readable message on bad input."""
    if any(ch in root for ch in "*?["):
        raise ValueError(
            f"root must be a repository directory, not a glob ({root!r}) — "
            "FTS derives its own globs from the root."
        )
    p = Path(root).expanduser()
    try:
        p = p.resolve()
    except OSError as e:  # pragma: no cover - resolve rarely raises
        raise ValueError(f"could not resolve root {root!r}: {e}") from e
    if not p.is_dir():
        raise ValueError(f"root {str(p)!r} is not an existing directory.")
    return p


def _fts_con_for_root(mcp, root: str):
    """Get-or-build a cached FTS connection scoped to ``root`` (LRU-bounded).

    Builds ``Plucker(repo=root)`` + ``ensure_fts()`` on first request for a root (~1s),
    caches it, and closes the least-recently-used connection past ``_FTS_CACHE_MAX``.
    Returns the fledgling Connection to run the FTS macro against. May raise ValueError."""
    abs_root = _resolve_fts_root(root)
    key = str(abs_root)
    with _fts_lock:
        cache = getattr(mcp, "_fts_servers", None)
        if cache is None:
            cache = mcp._fts_servers = OrderedDict()
        entry = cache.get(key)
        if entry is not None:
            cache.move_to_end(key)
            return entry["con"]
        # Same plugins as the server connection (AstViewer + Search).
        from pluckit.pluckins.search import Search
        from pluckit.pluckins.viewer import AstViewer
        pk = Plucker(repo=key, plugins=[AstViewer, Search])
        con = pk.connection
        try:
            con.ensure_fts()
        except Exception:  # pragma: no cover - depends on repo shape
            # Some repos (e.g. no markdown to index) make the full FTS build raise.
            # Don't crash the search tool — cache the connection anyway; the query then
            # returns whatever was indexed, or the fail-loud empty message via tool_fn.
            pass
        cache[key] = {"plucker": pk, "con": con}
        cache.move_to_end(key)
        while len(cache) > _FTS_CACHE_MAX:
            _, old = cache.popitem(last=False)
            try:
                old["con"].close()
            except Exception:  # pragma: no cover - best-effort close
                pass
        return con


def _register_tool(
    mcp,  # FastMCP type annotation removed to avoid import at module level
    con,
    presentation: ToolPresentation,
    defaults: ProjectDefaults,
    cache: SessionCache,
    access_log: AccessLog,
):
    """Register a single macro as an MCP tool."""
    if presentation.executor:
        _register_executor_tool(mcp, presentation)
        return

    tool_name = presentation.name
    macro_name = presentation.macro_name
    params = presentation.params
    description = presentation.description
    is_text = presentation.format == "text"
    numeric_params = presentation.numeric_params
    is_fts = macro_name in _FTS_MACROS

    if presentation.max_lines is not None:
        limit_param = "max_lines"
        default_limit = presentation.max_lines
    elif presentation.max_rows is not None:
        limit_param = "max_results"
        default_limit = presentation.max_rows
    else:
        limit_param = None
        default_limit = 0

    range_params = presentation.range_params
    cache_ttl = presentation.cache_ttl
    cache_mtime_params = presentation.cache_mtime_params

    # Build the tool function dynamically
    # FastMCP uses the function signature for parameter schema
    async def tool_fn(**kwargs) -> str:
        t0 = _time.time()

        # Apply smart defaults for None params
        kwargs = apply_defaults(defaults, macro_name, kwargs)

        # FTS opt-in: a `root` selects WHICH repository to full-text search. Popped here so
        # it never reaches the macro args; without it, FTS uses the server's own project.
        fts_root = kwargs.pop("root", None) if is_fts else None

        # Extract truncation parameter before passing to SQL macro
        max_rows = default_limit
        if limit_param and limit_param in kwargs:
            val = kwargs.pop(limit_param)
            if val is not None:
                try:
                    max_rows = int(val)
                except (TypeError, ValueError):
                    pass  # keep default_limit

        # Skip truncation if user provided a range-narrowing parameter
        if range_params and any(kwargs.get(p) is not None for p in range_params):
            max_rows = 0

        # Remove None values; coerce known numeric params to int.
        # Only numeric_params are coerced — blanket isdigit() would
        # break git SHAs like "1234567".
        filtered = {}
        for k, v in kwargs.items():
            if v is None:
                continue
            if k in numeric_params and isinstance(v, str) and v.isdigit():
                filtered[k] = int(v)
            else:
                filtered[k] = v

        # Build cache args (include limit param since it affects output)
        cache_args = dict(filtered)
        if limit_param and max_rows != default_limit:
            cache_args[limit_param] = max_rows
        if fts_root:
            cache_args["root"] = fts_root  # cache FTS results per searched repo

        # Check cache
        if cache_ttl is not None:
            cached = cache.get(tool_name, cache_args)
            if cached is not None:
                elapsed = (_time.time() - t0) * 1000
                access_log.record(tool_name, cache_args, cached.row_count,
                                  cached=True, elapsed_ms=elapsed)
                age = int(cached.age_seconds())
                return f"(cached — same as {age}s ago)\n{cached.text}"

        # FTS search needs an index. Default target = the server's project (built lazily).
        # If a `root` was given, full-text-search THAT repo via a cached per-root index.
        target_con = con
        if is_fts:
            if fts_root:
                try:
                    target_con = _fts_con_for_root(mcp, fts_root)
                except ValueError as e:
                    return f"(invalid root: {e})"
            else:
                _ensure_fts(con)

        def _empty_msg() -> str:
            # A bare "(no results)" from FTS was read by agents as "symbol doesn't exist".
            # Say what was searched and what FTS actually indexes, so empty is interpretable.
            if is_fts and fts_root:
                return (
                    f"(no full-text matches in `{fts_root}`. FTS indexes definition names, "
                    "string literals, comments, and doc sections — not bare code tokens; "
                    "try a name/string term, or a structural query via find / find_names.)"
                )
            if is_fts:
                return (
                    "(no matches in this server's indexed project — code_pattern "
                    f"`{defaults.code_pattern}`. Full-text search defaults to the server's "
                    "project; pass `root=<repo dir>` to full-text-search a different "
                    "repository, or use the structural tools — find / view / find_names / "
                    "read_source — with an explicit `source` glob.)"
                )
            return "(no results)"

        # Call macro (against the per-root index when a `root` was given)
        macro = getattr(target_con, macro_name)
        try:
            rel = macro(**filtered)
            cols = rel.columns
            rows = rel.fetchall()
        except Exception as e:
            etype = type(e).__name__
            if etype in ("IOException", "InvalidInputException"):
                elapsed = (_time.time() - t0) * 1000
                access_log.record(tool_name, cache_args, 0,
                                  cached=False, elapsed_ms=elapsed)
                return _empty_msg()
            raise
        if not rows:
            elapsed = (_time.time() - t0) * 1000
            access_log.record(tool_name, cache_args, 0,
                              cached=False, elapsed_ms=elapsed)
            return _empty_msg()

        total_rows = len(rows)

        # Apply truncation
        omission = None
        if limit_param and max_rows > 0:
            rows, omission = _truncate_rows(rows, max_rows, macro_name)
        displayed_rows = len(rows)

        # Format output
        if is_text:
            if len(cols) == 1:
                lines = [str(r[0]) for r in rows]
            elif "line_number" in cols and "content" in cols:
                ln_idx = cols.index("line_number")
                ct_idx = cols.index("content")
                lines = [f"{r[ln_idx]:4d}  {r[ct_idx]}" for r in rows]
            else:
                lines = []
                for row in rows:
                    parts = [str(v) for v in row if v is not None]
                    lines.append("  ".join(parts))
            if omission:
                lines.insert(_HEAD_TAIL, omission)
            text = "\n".join(lines)
        else:
            text = _format_markdown_table(cols, rows)
            if omission:
                md_lines = text.split("\n")
                insert_at = 2 + _HEAD_TAIL
                md_lines.insert(insert_at, omission)
                text = "\n".join(md_lines)

        # Make the searched corpus explicit when FTS ran against a per-call root.
        if is_fts and fts_root:
            text = f"(full-text search of `{fts_root}`)\n{text}"

        elapsed = (_time.time() - t0) * 1000

        # Store in cache
        if cache_ttl is not None:
            file_mtimes = {}
            for p in cache_mtime_params:
                path = filtered.get(p)
                if path:
                    try:
                        file_mtimes[path] = Path(path).stat().st_mtime
                    except OSError:
                        pass
            cache.put(tool_name, cache_args, text, displayed_rows,
                      ttl=cache_ttl, file_mtimes=file_mtimes)

        # Log access
        access_log.record(tool_name, cache_args, displayed_rows,
                          cached=False, elapsed_ms=elapsed)

        return text

    # Set function metadata for FastMCP
    tool_fn.__name__ = tool_name
    tool_fn.__qualname__ = tool_name
    if is_fts:
        description = (
            description.rstrip()
            + "\n\nBy default this searches the server's own project. To full-text-search a "
            "DIFFERENT repository, pass `root=<repository directory>` (an absolute path) — the "
            "repo is indexed on first use and cached."
        )
    tool_fn.__doc__ = description

    # Build parameter annotations for FastMCP schema generation.
    # All params get default=None so FastMCP validation passes even when
    # the caller omits them — apply_defaults fills them in at runtime.
    annotations = {}
    sig_params = []
    for p in params:
        annotations[p] = Optional[str]
        sig_params.append(inspect.Parameter(
            p, inspect.Parameter.KEYWORD_ONLY, default=None,
            annotation=Optional[str],
        ))
    if limit_param:
        annotations[limit_param] = Optional[int]
        sig_params.append(inspect.Parameter(
            limit_param,
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=Optional[int],
        ))
    if is_fts:
        # Opt-in target: full-text-search a repository other than the server's project.
        annotations["root"] = Optional[str]
        sig_params.append(inspect.Parameter(
            "root", inspect.Parameter.KEYWORD_ONLY, default=None,
            annotation=Optional[str],
        ))
    tool_fn.__annotations__ = {**annotations, "return": str}

    tool_fn.__signature__ = inspect.Signature(
        sig_params,
        return_annotation=str,
    )

    mcp.add_tool(tool_fn)


# ── Entry point ──────────────────────────────────────────────────────

def main():
    """Run the fledgling MCP server."""
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()
