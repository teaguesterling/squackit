# squackit/tools.py
"""Pluckit-backed tools for squackit's tool namespace.

These tools wrap pluckit's CSS selector API and are registered alongside
fledgling macro tools. They take priority over fledgling equivalents
(find_definitions, code_structure, complexity_hotspots, select_code).
"""

from __future__ import annotations

import os

from fledgling.tools import ToolInfo
from squackit.tool_config import ToolPresentation


def _filtered_source(plucker, source: str) -> str:
    """De-vendor a source glob before it reaches pluckit's AST engine.

    A bare ``**/*`` glob over a repo with git submodules or checked-in
    third-party trees (googletest, vendored deps) makes the AST tools parse
    thousands of files that aren't the project's own code — the ``find`` /
    ``view`` / ``complexity`` flood. We reuse fledgling's single-source-of-truth
    ignore policy (``_is_vendored_path`` denylist + ``_submodule_prefixes``
    git-awareness) to expand the glob, drop the vendored files, and hand pluckit
    an explicit ``read_ast`` table of just the survivors via its existing
    table-name source path. sitting_duck parses a list of paths exactly as it
    parses a glob (verified identical results), so this changes only *which*
    files are parsed, not how selectors match.

    Returns the original ``source`` unchanged — so pluckit handles it directly —
    when filtering doesn't apply or would be wrong:
      * not a glob (a single file path or a DuckDB table/view name) — an
        explicit target, nothing to de-flood;
      * the glob expands to <= 1 file;
      * filtering removes *everything* — the caller deliberately aimed at a
        vendored/submodule tree (e.g. ``rdkit/**/*.cpp``), so honor it;
      * filtering removes *nothing* — passing the glob through is cheaper and
        gives identical results.
    Otherwise returns the name of a TEMP table holding the filtered AST.

    Degrades gracefully: if the fledgling ignore-policy macros can't run for any
    reason (not loaded, SQL error), we fall back to the raw ``source`` — the
    caller gets the historical unfiltered (flooded) behavior rather than a dead
    tool. This is a de-flooding optimization, not a correctness gate, so a raw
    glob is a safe answer; never let it take down find/view/complexity.
    """
    if "*" not in source:
        return source

    try:
        db = plucker._ctx.db
        resolved = (
            source if os.path.isabs(source)
            else os.path.join(plucker._ctx.repo, source)
        )
        # Submodule exclusion reads <root>/.gitmodules, so root must be the repo
        # that actually contains the globbed files — NOT the plucker's cwd, which
        # may be a different project entirely. Derive it from the glob's literal
        # prefix (the path before the first wildcard) and walk up to the nearest
        # .gitmodules / .git. The denylist is absolute-pattern based, no root needed.
        prefix = resolved.split("*", 1)[0]
        root = prefix if prefix.endswith("/") else os.path.dirname(prefix)
        while root and root != "/":
            if os.path.exists(os.path.join(root, ".gitmodules")) or os.path.exists(
                os.path.join(root, ".git")
            ):
                break
            root = os.path.dirname(root)
        rq = resolved.replace("'", "''")
        rootq = root.rstrip("/").replace("'", "''")

        total = db.sql(f"SELECT count(*) FROM glob('{rq}')").fetchone()[0]
        if total <= 1:
            return source

        kept = [
            r[0]
            for r in db.sql(
                f"SELECT file FROM glob('{rq}') "
                f"WHERE NOT _is_vendored_path(file) "
                f"AND NOT EXISTS (SELECT 1 FROM _submodule_prefixes('{rootq}') s "
                f"WHERE file LIKE s.prefix || '%') "
                f"ORDER BY file"
            ).fetchall()
        ]
        if not kept or len(kept) == total:
            return source

        lit = "[" + ", ".join("'" + f.replace("'", "''") + "'" for f in kept) + "]"
        db.execute(
            "CREATE OR REPLACE TEMP TABLE _squackit_src AS "
            f"SELECT * FROM read_ast({lit}, peek := 'none+schema')"
        )
        return "_squackit_src"
    except Exception:
        # Ignore-policy macros unavailable / SQL error — fall back to the raw
        # glob. Unfiltered (flooded) results beat a broken tool.
        return source


def _make_plucker(source: str):
    """Create a Plucker with AstViewer and Search for tool execution.

    The source glob is de-vendored first (see :func:`_filtered_source`) so the
    AST tools focus on the project's own code instead of drowning in submodules,
    build output, and checked-in third-party trees.
    """
    from pluckit import Plucker
    from pluckit.pluckins.search import Search
    from pluckit.pluckins.viewer import AstViewer
    p = Plucker(plugins=[AstViewer, Search])
    p._code_source = _filtered_source(p, source)
    return p


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
    return [step.op for step in chain.steps if step.op in _Chain.MUTATION_OPS]


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
    pluckins = getattr(plucker, "pluckins", None)
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
                    "names, line ranges, and a peek of the source. "
                    "Truncated to 50 rows by default. "
                    "Pass verbose=true for the full AST bookkeeping columns "
                    "(node_id, depth, sibling_index, semantic_type, etc.).",
        required=["source", "selector"],
    ),
    max_rows=50,
    # Default projection keeps the four columns callers actually use; the rest
    # are internal AST bookkeeping noise unless the caller asks for verbose.
    compact_columns=("file_path", "start_line", "end_line", "name", "peek"),
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
