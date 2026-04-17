"""Squackit kit for lackpy.

Registers squackit's MCP tools as lackpy ToolSpecs so a small local model
can generate restricted Python programs that delegate code-intelligence
work to squackit.

Usage::

    from lackpy import LackpyService
    from squackit.lackpy_integration import register_squackit_kit

    svc = LackpyService()
    register_squackit_kit(svc.toolbox)
    # Now svc.toolbox knows about view, find, find_names, etc.

    result = await svc.delegate(
        "find all test functions",
        kit=["find_names"],
    )

The provider calls the real squackit executors directly — no MCP
serialization overhead when lackpy and squackit share a process.
"""

from __future__ import annotations

from typing import Any, Callable


def register_squackit_kit(toolbox: Any) -> None:
    """Register the squackit provider and all squackit tool specs.

    Idempotent: safe to call multiple times.
    """
    try:
        toolbox.register_provider(SquackitProvider())
    except ValueError:
        pass
    for spec in SQUACKIT_TOOLS:
        try:
            toolbox.register_tool(spec)
        except ValueError:
            pass


class SquackitProvider:
    """Lackpy provider that dispatches to squackit's tool executors."""

    @property
    def name(self) -> str:
        return "squackit"

    def available(self) -> bool:
        try:
            import squackit.tools  # noqa: F401
            return True
        except ImportError:
            return False

    def resolve(self, tool_spec: Any) -> Callable[..., Any]:
        implementations: dict[str, Callable] = {
            "view": _view_tool,
            "find": _find_tool,
            "find_names": _find_names_tool,
            "complexity": _complexity_tool,
            "read_source": _read_source_tool,
        }
        fn = implementations.get(tool_spec.name)
        if fn is None:
            raise KeyError(f"No squackit implementation for {tool_spec.name!r}")
        return fn


# ── Thin wrappers that normalize return types for lackpy ──────────────
# Lackpy tools should return plain Python values (list, str, int, dict),
# not DuckDB relations or View objects.


def _view_tool(source: str, selector: str) -> str:
    """Return rendered markdown of matched nodes."""
    from squackit.tools import view_executor
    result = view_executor(source=source, selector=selector)
    return result.markdown if hasattr(result, "markdown") else str(result)


def _find_tool(source: str, selector: str) -> list[dict]:
    """Return matched AST nodes as a list of dicts."""
    from squackit.tools import find_executor
    rel = find_executor(source=source, selector=selector)
    cols = rel.columns
    rows = rel.fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _find_names_tool(source: str, selector: str) -> list[str]:
    """Return names of AST nodes matching selector as a list of strings."""
    from squackit.tools import find_names_executor
    return find_names_executor(source=source, selector=selector)


def _complexity_tool(source: str, selector: str) -> list[dict]:
    """Return matched nodes ranked by complexity as a list of dicts."""
    from squackit.tools import complexity_executor
    rel = complexity_executor(source=source, selector=selector)
    cols = rel.columns
    rows = rel.fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _read_source_tool(file_path: str, lines: str | None = None) -> str:
    """Read file content with optional line range ('10-20')."""
    from pathlib import Path
    text = Path(file_path).read_text()
    if lines is None:
        return text
    if "-" in lines:
        start, end = lines.split("-", 1)
        all_lines = text.splitlines(keepends=True)
        start_i = max(0, int(start) - 1)
        end_i = int(end)
        return "".join(all_lines[start_i:end_i])
    # Single line number
    line_no = int(lines)
    all_lines = text.splitlines(keepends=True)
    return all_lines[line_no - 1] if 0 < line_no <= len(all_lines) else ""


# ── ToolSpec definitions ──────────────────────────────────────────────
# Import at module level so callers can iterate SQUACKIT_TOOLS without
# needing lackpy imported first. The TYPE_CHECKING-style forward ref
# keeps the import cost low.


def _make_tool_specs() -> list[Any]:
    from lackpy import ArgSpec, ToolSpec  # type: ignore

    return [
        ToolSpec(
            name="view",
            provider="squackit",
            description=(
                "Render source code matching a CSS-like AST selector as markdown. "
                "Use for 'show me function X' or 'show me the body of the class'."
            ),
            args=[
                ArgSpec(name="source", type="str",
                        description="Glob pattern for files (e.g. 'src/**/*.py')."),
                ArgSpec(name="selector", type="str",
                        description="CSS selector: .fn#name for a function, .class#Name for a class, .class > .fn for methods."),
            ],
            returns="str",
            grade_w=0, effects_ceiling=0,
            examples=[
                {
                    "intent": "show me the validate_token function",
                    "code": "view(source='src/**/*.py', selector='.fn#validate_token')",
                    "tags": ["view", "function"],
                },
                {
                    "intent": "show the AuthService class",
                    "code": "view(source='src/**/*.py', selector='.class#AuthService')",
                    "tags": ["view", "class"],
                },
            ],
        ),
        ToolSpec(
            name="find",
            provider="squackit",
            description=(
                "Find AST nodes matching a CSS selector. Returns a list of dicts "
                "with name, file_path, start_line, end_line, and other metadata."
            ),
            args=[
                ArgSpec(name="source", type="str",
                        description="Glob pattern for files (e.g. 'src/**/*.py')."),
                ArgSpec(name="selector", type="str",
                        description="CSS selector: .fn, .class, .fn[name^='test_'], etc."),
            ],
            returns="list[dict]",
            grade_w=0, effects_ceiling=0,
            examples=[
                {
                    "intent": "find all classes",
                    "code": "find(source='src/**/*.py', selector='.class')",
                    "tags": ["find", "class"],
                },
                {
                    "intent": "find all test functions",
                    "code": "find(source='tests/**/*.py', selector=\".fn[name^='test_']\")",
                    "tags": ["find", "test"],
                },
            ],
        ),
        ToolSpec(
            name="find_names",
            provider="squackit",
            description=(
                "Returns names of functions/classes/etc. matching a selector. "
                "Call this tool DIRECTLY — do not open files, do not define "
                "helper functions, do not use os/Path. "
                "Selector syntax: '.fn' for functions, '.class' for classes, "
                "'.fn#foo' for a function named foo. "
                "Never pass bare words like 'function' — use the dot-shorthand."
            ),
            args=[
                ArgSpec(name="source", type="str",
                        description="Glob pattern for files, e.g. 'src/**/*.py'."),
                ArgSpec(name="selector", type="str",
                        description="CSS selector: '.fn' for functions, '.class' for classes, '.fn#name' for a specific function."),
            ],
            returns="list[str]",
            grade_w=0, effects_ceiling=0,
            examples=[
                {
                    "intent": "list all function names in tools.py",
                    "code": "find_names(source='squackit/tools.py', selector='.fn')",
                    "tags": ["find_names", "function"],
                },
                {
                    "intent": "list all functions in the package",
                    "code": "find_names(source='src/**/*.py', selector='.fn')",
                    "tags": ["find_names", "function"],
                },
                {
                    "intent": "list all classes",
                    "code": "find_names(source='src/**/*.py', selector='.class')",
                    "tags": ["find_names", "class"],
                },
                {
                    "intent": "list methods of the Handler class",
                    "code": "find_names(source='src/api.py', selector='.class#Handler .fn')",
                    "tags": ["find_names", "class", "method"],
                },
            ],
        ),
        ToolSpec(
            name="complexity",
            provider="squackit",
            description=(
                "Find AST nodes and rank them by complexity (descendant count). "
                "Use to identify the most complex functions/classes."
            ),
            args=[
                ArgSpec(name="source", type="str",
                        description="Glob pattern for files."),
                ArgSpec(name="selector", type="str",
                        description="CSS selector."),
            ],
            returns="list[dict]",
            grade_w=0, effects_ceiling=0,
            examples=[
                {
                    "intent": "find the most complex functions",
                    "code": "complexity(source='src/**/*.py', selector='.fn')",
                    "tags": ["complexity", "function"],
                },
            ],
        ),
        ToolSpec(
            name="read_source",
            provider="squackit",
            description=(
                "Read a file's text content, optionally restricted to a line range."
            ),
            args=[
                ArgSpec(name="file_path", type="str",
                        description="Path to the file."),
                ArgSpec(name="lines", type="str",
                        description="Line range as 'start-end' (e.g. '10-20'), or omit for whole file."),
            ],
            returns="str",
            grade_w=1, effects_ceiling=0,
            examples=[
                {
                    "intent": "read the first 20 lines of main.py",
                    "code": "read_source(file_path='main.py', lines='1-20')",
                    "tags": ["read_source"],
                },
            ],
        ),
    ]


def _load_curated_examples() -> dict[str, list[dict]]:
    """Load curated examples from data/examples.json, grouped by tool name."""
    import json
    from pathlib import Path
    data_path = Path(__file__).parent / "data" / "examples.json"
    if not data_path.exists():
        return {}
    data = json.loads(data_path.read_text())
    by_tool: dict[str, list[dict]] = {}
    for ex in data.get("examples", []):
        tool = ex.get("tool", "")
        entry = {"intent": ex["intent"], "code": ex["code"], "tags": ex.get("tags", [])}
        if "correct_code" in ex:
            entry["correct_code"] = ex["correct_code"]
        if "notes" in ex:
            entry["notes"] = ex["notes"]
        by_tool.setdefault(tool, []).append(entry)
    return by_tool


# Lazy — only build if lackpy is available at import time
try:
    SQUACKIT_TOOLS: list[Any] = _make_tool_specs()
    # Enrich ToolSpecs with curated examples from data/examples.json
    _curated = _load_curated_examples()
    for spec in SQUACKIT_TOOLS:
        extras = _curated.get(spec.name, [])
        if extras:
            spec.examples = extras
except ImportError:
    SQUACKIT_TOOLS = []
