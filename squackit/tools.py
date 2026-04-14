# squackit/tools.py
"""Pluckit-backed tools for squackit's tool namespace.

These tools wrap pluckit's CSS selector API and are registered alongside
fledgling macro tools. They take priority over fledgling equivalents
(find_definitions, code_structure, complexity_hotspots, select_code).
"""

from __future__ import annotations

from fledgling.tools import ToolInfo
from squackit.tool_config import ToolPresentation


def _make_plucker(source: str):
    """Create a Plucker with AstViewer for tool execution."""
    from pluckit import Plucker
    from pluckit.plugins.viewer import AstViewer
    return Plucker(code=source, plugins=[AstViewer])


def view_executor(*, source: str, selector: str):
    """Execute a view query, returning rendered source code."""
    p = _make_plucker(source)
    return p.view(selector)


def find_executor(*, source: str, selector: str):
    """Execute a find query, returning matched AST nodes as a relation."""
    p = _make_plucker(source)
    return p.find(selector).relation


def find_names_executor(*, source: str, selector: str) -> list[str]:
    """Execute a find query, returning just the names."""
    p = _make_plucker(source)
    return p.find(selector).names()


def complexity_executor(*, source: str, selector: str):
    """Execute a find query with complexity metrics, ranked by complexity."""
    p = _make_plucker(source)
    sel = p.find(selector)
    view_name = sel._register("cx")
    try:
        rel = sel._ctx.db.sql(
            f"SELECT name, file_path, start_line, end_line, "
            f"descendant_count AS complexity, peek AS signature "
            f"FROM {view_name} ORDER BY descendant_count DESC"
        )
    except Exception:
        sel._unregister(view_name)
        raise
    return rel


def pluck_executor(*, argv: str):
    """Execute a pluckit chain from a whitespace-separated command string.

    Accepts the same grammar as `squackit pluck` on the CLI:
        "source_pattern [method [arg]]... [terminal]"

    Returns a JSON-serialized chain result: {chain, type, data}.

    Examples:
        pluck(argv="**/*.py find .fn names")
        pluck(argv="--plugin AstViewer src/api.py find .fn#handler view")
        pluck(argv="**/*.py find .fn names reset find .class names")
    """
    import shlex
    import json
    from pluckit import Chain

    tokens = shlex.split(argv)
    if not tokens:
        return json.dumps({"error": "Empty argv"}, indent=2)

    chain = Chain.from_argv(tokens)
    result = chain.evaluate()
    return json.dumps(result, indent=2, default=str)


# -- Tool definitions --

VIEW_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="view",
        params=["source", "selector"],
        description="View source code matching CSS selectors. Returns rendered "
                    "markdown with file headings and source blocks.",
        required=["source", "selector"],
    ),
    format_override="text",
    executor=view_executor,
)

FIND_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="find",
        params=["source", "selector"],
        description="Find AST nodes matching CSS selectors. Returns file paths, "
                    "names, line ranges.",
        required=["source", "selector"],
    ),
    executor=find_executor,
)

FIND_NAMES_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="find_names",
        params=["source", "selector"],
        description="Find names of AST nodes matching CSS selectors.",
        required=["source", "selector"],
    ),
    executor=find_names_executor,
)

COMPLEXITY_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="complexity",
        params=["source", "selector"],
        description="Find AST nodes matching CSS selectors, ranked by complexity.",
        required=["source", "selector"],
    ),
    executor=complexity_executor,
)

PLUCK_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="pluck",
        params=["argv"],
        description=(
            "Execute a pluckit chain query. Pass a whitespace-separated "
            "command: 'source_pattern [method [arg]]... [terminal]'. "
            "Terminals: names, count, text, materialize, view, complexity. "
            "Use 'reset' to start a new chain from the source. "
            "Example: '**/*.py find .fn containing cache names'. "
            "Use '--plugin AstViewer' prefix for view terminals. "
            "Returns JSON: {chain, type, data}."
        ),
        required=["argv"],
    ),
    format_override="text",
    executor=pluck_executor,
)

PLUCKIT_TOOLS = [VIEW_TOOL, FIND_TOOL, FIND_NAMES_TOOL, COMPLEXITY_TOOL, PLUCK_TOOL]
