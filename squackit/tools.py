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
    from pluckit.pluckins.viewer import AstViewer
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


def _chain_mutation_ops(chain) -> list[str]:
    """Return the list of mutation op names present in the chain (in order)."""
    from pluckit.chain import Chain as _Chain
    return [step.op for step in chain.steps if step.op in _Chain._MUTATION_OPS]


def collect_pluckin_tools(plucker) -> list:
    """Collect squackit tools from a Plucker's registered pluckins.

    Pluckins that want to contribute squackit tools expose a
    ``squackit_tools()`` method returning a list of ToolPresentation
    objects. This function walks the Plucker's pluckin registry and
    collects tools from any pluckin that implements the method.

    Plugin authors can add squackit integration without depending on
    squackit at import time — the import lives inside the method body
    and only fires when squackit actually calls it.
    """
    tools: list = []
    registry = getattr(plucker, "_registry", None)
    if registry is None:
        return tools
    pluckins = getattr(registry, "pluckins", None)
    if pluckins is None:
        return tools
    for pluckin in pluckins:
        fn = getattr(pluckin, "squackit_tools", None)
        if callable(fn):
            try:
                tools.extend(fn())
            except Exception:
                # A broken pluckin shouldn't break the whole registry.
                # Squackit's server/CLI will surface the error contextually.
                pass
    return tools


def pluck_executor(*, argv: str, allow_mutations: str | bool = False):
    """Execute a pluckit chain from a whitespace-separated command string.

    Accepts the same grammar as `squackit pluck` on the CLI:
        "source_pattern [method [arg]]... [terminal]"

    **Mutation safety:** chains containing mutation operations (rename,
    replaceWith, wrap, remove, etc.) are blocked by default. Pass
    ``allow_mutations=true`` to opt in. Agents should only enable this
    when the user has explicitly authorized code changes.

    Returns a JSON-serialized chain result: {chain, type, data}.

    Examples:
        pluck(argv="**/*.py find .fn names")
        pluck(argv="--plugin AstViewer src/api.py find .fn#handler view")
        pluck(argv="**/*.py find .fn#old rename new_name", allow_mutations=True)
    """
    import shlex
    import json
    from pluckit import Chain

    tokens = shlex.split(argv)
    if not tokens:
        return json.dumps({"error": "Empty argv"}, indent=2)

    chain = Chain.from_argv(tokens)

    # Coerce string "true"/"false" from MCP clients to bool
    if isinstance(allow_mutations, str):
        allow = allow_mutations.lower() in ("true", "1", "yes")
    else:
        allow = bool(allow_mutations)

    mutations = _chain_mutation_ops(chain)
    if mutations and not allow:
        return json.dumps({
            "error": "blocked: chain contains mutation operations",
            "mutations": mutations,
            "hint": "Set allow_mutations=true to enable. Mutations modify "
                    "source files — ensure the user has authorized changes.",
            "chain": chain.to_dict(),
        }, indent=2)

    result = chain.evaluate()
    return json.dumps(result, indent=2, default=str)


# -- Tool definitions --

VIEW_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="view",
        params=["source", "selector"],
        description="View source code matching CSS selectors. Returns rendered "
                    "markdown with file headings and source blocks. "
                    "Truncated to 20 blocks by default; pass max_results to raise.",
        required=["source", "selector"],
    ),
    format_override="text",
    max_rows=20,
    executor=view_executor,
)

FIND_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="find",
        params=["source", "selector"],
        description="Find AST nodes matching CSS selectors. Returns file paths, "
                    "names, line ranges. Truncated to 50 rows by default.",
        required=["source", "selector"],
    ),
    max_rows=50,
    executor=find_executor,
)

FIND_NAMES_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="find_names",
        params=["source", "selector"],
        description="Find names of AST nodes matching CSS selectors. "
                    "Truncated to 100 names by default.",
        required=["source", "selector"],
    ),
    max_rows=100,
    executor=find_names_executor,
)

COMPLEXITY_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="complexity",
        params=["source", "selector"],
        description="Find AST nodes matching CSS selectors, ranked by complexity. "
                    "Truncated to 30 rows by default — only the top complexity "
                    "items are usually interesting.",
        required=["source", "selector"],
    ),
    max_rows=30,
    executor=complexity_executor,
)

PLUCK_TOOL = ToolPresentation(
    info=ToolInfo(
        macro_name="pluck",
        params=["argv", "allow_mutations"],
        description=(
            "Execute a pluckit chain query. Pass a whitespace-separated "
            "command: 'source_pattern [method [arg]]... [terminal]'. "
            "Terminals: names, count, text, materialize, view, complexity. "
            "Use 'reset' to start a new chain from the source. "
            "Example: '**/*.py find .fn containing cache names'. "
            "Use '--plugin AstViewer' prefix for view terminals. "
            "Mutations (rename, replaceWith, wrap, etc.) are blocked "
            "unless allow_mutations=true. Returns JSON: {chain, type, data}."
        ),
        required=["argv"],
    ),
    format_override="text",
    executor=pluck_executor,
)

PLUCKIT_TOOLS = [VIEW_TOOL, FIND_TOOL, FIND_NAMES_TOOL, COMPLEXITY_TOOL, PLUCK_TOOL]
