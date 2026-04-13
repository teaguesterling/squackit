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

    con = Plucker(repo=root, profile=profile, modules=modules, init=init).connection
    mcp = FastMCP(name)

    # Infer smart defaults, merge with config file overrides
    project_root = Path(root) if root else Path.cwd()
    overrides = load_config(project_root)
    defaults = infer_defaults(con, overrides=overrides, root=project_root)
    mcp._defaults = defaults

    cache = SessionCache()
    access_log = AccessLog(con._con)
    mcp.session_cache = cache
    mcp.access_log = access_log

    # Register each macro as an MCP tool
    from squackit.tools import PLUCKIT_TOOLS
    registry = build_tool_registry(con._tools, extra_tools=PLUCKIT_TOOLS)
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

    async def tool_fn(**kwargs) -> str:
        filtered = {k: v for k, v in kwargs.items() if v is not None}

        try:
            result = executor(**filtered)
        except Exception as e:
            etype = type(e).__name__
            if etype == "PluckerError":
                return f"Error: {e}"
            raise

        # View -> markdown
        if hasattr(result, 'markdown'):
            return result.markdown or "(no results)"
        # DuckDB relation -> table
        if hasattr(result, 'columns') and hasattr(result, 'fetchall'):
            cols = result.columns
            rows = result.fetchall()
            if not rows:
                return "(no results)"
            if is_text:
                lines = []
                for row in rows:
                    parts = [str(v) for v in row if v is not None]
                    lines.append("  ".join(parts))
                return "\n".join(lines)
            return _format_markdown_table(cols, rows)
        # list -> joined
        if isinstance(result, list):
            return "\n".join(str(item) for item in result) if result else "(no results)"
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
    tool_fn.__annotations__ = {**annotations, "return": str}
    tool_fn.__signature__ = inspect.Signature(
        sig_params, return_annotation=str,
    )

    mcp.add_tool(tool_fn)


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

        # Check cache
        if cache_ttl is not None:
            cached = cache.get(tool_name, cache_args)
            if cached is not None:
                elapsed = (_time.time() - t0) * 1000
                access_log.record(tool_name, cache_args, cached.row_count,
                                  cached=True, elapsed_ms=elapsed)
                age = int(cached.age_seconds())
                return f"(cached — same as {age}s ago)\n{cached.text}"

        # Call macro
        macro = getattr(con, macro_name)
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
                return "(no results)"
            raise
        if not rows:
            elapsed = (_time.time() - t0) * 1000
            access_log.record(tool_name, cache_args, 0,
                              cached=False, elapsed_ms=elapsed)
            return "(no results)"

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
