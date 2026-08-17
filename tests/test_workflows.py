"""Tests for fledgling compound workflow tools.

Tests the compound tools (explore, investigate, review, search) that
orchestrate multiple fledgling macros in a single call.
"""

import asyncio
from pathlib import Path

import pytest

from conftest import PROJECT_ROOT, requires_fledgling_source

try:
    import fastmcp  # noqa: F401
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False

requires_fastmcp = pytest.mark.skipif(
    not HAS_FASTMCP, reason="fastmcp not installed"
)


# ── Unit tests for helpers ─────────────────────────────────────────


class TestFormatBriefing:
    """Test the _format_briefing helper."""

    def test_produces_markdown_with_title(self):
        from squackit.workflows import _format_briefing
        result = _format_briefing("My Title", [("Section A", "content a")])
        assert result.startswith("## My Title")

    def test_sections_have_headings(self):
        from squackit.workflows import _format_briefing
        result = _format_briefing("T", [
            ("Alpha", "aaa"),
            ("Beta", "bbb"),
        ])
        assert "### Alpha" in result
        assert "### Beta" in result
        assert "aaa" in result
        assert "bbb" in result

    def test_empty_sections_list(self):
        from squackit.workflows import _format_briefing
        result = _format_briefing("Empty", [])
        assert "## Empty" in result

    def test_section_order_preserved(self):
        from squackit.workflows import _format_briefing
        result = _format_briefing("T", [
            ("First", "111"),
            ("Second", "222"),
            ("Third", "333"),
        ])
        assert result.index("First") < result.index("Second") < result.index("Third")


class TestSection:
    """Test the _section helper."""

    def test_returns_content_on_success(self):
        from squackit.workflows import _section
        heading, content = _section("Test", lambda: "hello")
        assert heading == "Test"
        assert content == "hello"

    def test_returns_error_note_on_exception(self):
        from squackit.workflows import _section
        heading, content = _section("Bad", lambda: 1 / 0)
        assert heading == "Bad"
        assert "could not load" in content.lower()

    def test_returns_no_data_when_empty(self):
        from squackit.workflows import _section
        heading, content = _section("Empty", lambda: "")
        assert heading == "Empty"
        assert "no data" in content.lower()

    def test_returns_no_data_when_none(self):
        from squackit.workflows import _section
        heading, content = _section("Nil", lambda: None)
        assert heading == "Nil"
        assert "no data" in content.lower()


class TestHasModule:
    """Test the _has_module helper."""

    def test_detects_loaded_module(self, all_macros):
        from squackit.workflows import _has_module
        # all_macros loads all modules including "source"
        assert _has_module(all_macros, "source") is True

    def test_rejects_missing_module(self, all_macros):
        from squackit.workflows import _has_module
        assert _has_module(all_macros, "nonexistent") is False


# ── Integration test helpers ───────────────────────────────────────


def _text(result) -> str:
    """Extract text from a FastMCP ToolResult."""
    return result.content[0].text


@pytest.fixture(scope="module")
def mcp():
    """Create a fledgling FastMCP server for testing."""
    pytest.importorskip("fastmcp")
    from squackit.server import create_server
    return create_server(root=PROJECT_ROOT, init=False)


def _run_async(coro):
    """Run an async coroutine, avoiding conflicts with pytest-asyncio."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _tool_names(mcp):
    """List all tool names from the server."""
    async def _list():
        from fastmcp import Client
        async with Client(mcp) as client:
            tools = await client.list_tools()
            return [t.name for t in tools]
    return _run_async(_list())


# ── Integration tests: explore ─────────────────────────────────────


@requires_fastmcp
class TestExplore:
    """Test the explore compound tool."""

    @pytest.fixture(scope="class")
    def text(self, mcp):
        return _text(_run_async(mcp.call_tool("explore", {})))

    def test_returns_non_empty(self, text):
        assert len(text) > 0

    def test_contains_languages_section(self, text):
        assert "Languages" in text

    def test_contains_definitions_section(self, text):
        assert "Key Definitions" in text

    def test_contains_documentation_section(self, text):
        assert "Documentation" in text

    def test_contains_recent_activity_section(self, text):
        assert "Recent Activity" in text

    def test_contains_python(self, text):
        """Dog-fooding: fledgling is a Python project."""
        assert "Python" in text

    def test_tool_is_registered(self, mcp):
        assert "explore" in _tool_names(mcp)


# ── Integration tests: investigate ─────────────────────────────────


@requires_fastmcp
class TestInvestigate:
    """Test the investigate compound tool.

    The section assertions below need a fledgling SOURCE checkout as the
    dog-food corpus. Against an installed wheel the corpus is site-packages,
    where the bundled sql/ outnumbers the Python, so the inferred code_pattern
    is legitimately `**/*.sql` and investigating a Python symbol finds nothing
    — the briefing then has no Definition/Source/Called-by sections. That is a
    fact about the corpus, not about investigate, and asserting it against a
    wheel sends anyone debugging it into squackit's scoping logic instead. The
    tests that hold either way (registration, unknown-name handling, project
    scoping) stay unmarked.
    """

    @pytest.fixture(scope="class")
    def text(self, mcp):
        return _text(_run_async(mcp.call_tool("investigate", {
            "name": "create_server",
        })))

    def test_returns_non_empty(self, text):
        assert len(text) > 0

    @requires_fledgling_source
    def test_contains_definition_section(self, text):
        assert "Definition" in text

    @requires_fledgling_source
    def test_contains_source_section(self, text):
        assert "Source" in text

    @requires_fledgling_source
    def test_contains_called_by_section(self, text):
        assert "Called by" in text

    def test_finds_function_name(self, text):
        assert "create_server" in text

    def test_unknown_name_returns_helpful_message(self, mcp):
        text = _text(_run_async(mcp.call_tool("investigate", {
            "name": "xyznonexistent999",
        })))
        assert "no definition found" in text.lower()

    def test_tool_is_registered(self, mcp):
        assert "investigate" in _tool_names(mcp)

    def test_scopes_to_project_by_default(self, mcp, tmp_path, monkeypatch):
        """Regression: `investigate(name="main")` used to substring-match
        across every indexed project, so a user in repo A would get hits
        from a vendored JS file in repo B. Results must come from the
        project this server was built for, and nowhere else.

        This originally asserted that invariant by chdir'ing to an EMPTY
        directory and requiring a miss — using cwd as a stand-in for "the
        current project". That stand-in only holds for a CLI run from
        inside the repo. A served corpus has an arbitrary cwd (whatever
        the launcher started in), so cwd-scoping searched a directory
        unrelated to the project; and once fledgling began sandboxing
        connections to the project root, a cwd outside that root failed
        the query outright rather than searching the wrong tree. Scoping
        now falls back to the served root, so the check below uses a
        FOREIGN symbol: cwd holds a definition the served project does
        not have, and it must not surface.
        """
        foreign = tmp_path / "other-project"
        foreign.mkdir()
        (foreign / "mod.py").write_text(
            "def foreign_only_symbol():\n    return 1\n")
        monkeypatch.chdir(foreign)

        text = _text(_run_async(mcp.call_tool("investigate", {
            "name": "foreign_only_symbol",
        })))
        assert "no definition found" in text.lower(), (
            "investigate leaked across project boundaries — found a symbol "
            "that exists only in cwd, not in the project this server serves"
        )

    def test_explicit_path_argument_overrides_cwd(self, mcp, tmp_path, monkeypatch):
        """When `path` is passed explicitly, investigate should scope to
        that path regardless of process cwd.
        """
        # chdir to an empty dir; pass the real squackit source as `path`.
        empty = tmp_path / "isolated2"
        empty.mkdir()
        monkeypatch.chdir(empty)

        import squackit
        squackit_root = str(Path(squackit.__file__).parent.parent)

        text = _text(_run_async(mcp.call_tool("investigate", {
            "name": "create_server",
            "path": squackit_root,
        })))
        # With explicit path, the symbol IS found even though cwd is empty.
        assert "create_server" in text, (
            "investigate(path=...) didn't scope to the requested path; "
            "should have found create_server but got: "
            + text[:200]
        )


# ── Unit tests: investigate exact-name preference ──────────────────


class _Rel:
    """Minimal stand-in for a fledgling relation (columns + fetchall)."""

    def __init__(self, columns, rows):
        self.columns = columns
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeCon:
    """Fake connection exposing just the macros investigate() calls.

    find_definitions emulates the real `name LIKE '%needle%'` substring macro
    so we can prove investigate's Python-side exact-match preference.
    """

    _DEF_COLS = [
        "file_path", "name", "kind", "start_line", "end_line", "signature",
    ]

    def __init__(self, defs):
        self._defs = defs  # list of DEF_COLS-shaped tuples

    def find_definitions(self, file_pattern, name_pattern):
        needle = name_pattern.strip("%")
        rows = [d for d in self._defs if needle in d[1]]
        return _Rel(self._DEF_COLS, rows)

    def function_callers(self, file_pattern, func_name):
        return _Rel(["file_path", "call_line", "caller_name"], [])

    def read_source(self, file_path, lines):
        return _Rel(["line_number", "content"], [])

    def find_in_ast(self, file_pattern, kind):
        return _Rel(["start_line", "name"], [])


class TestInvestigateExactMatch:
    """Regression: `investigate("ensure_loaded")` used to substring-match
    `_ensure_loaded` (and vendored copies), polluting the Definition table
    and — since Source/Calls key off defs[0] — sometimes describing the
    WRONG symbol entirely. Prefer exact name matches; fall back to substring
    only when nothing matches exactly.
    """

    def _con(self):
        return _FakeCon([
            ("a.py", "ensure_loaded", "DEFINITION_FUNCTION", 1, 5,
             "def ensure_loaded():"),
            ("vendored/cli.py", "_ensure_loaded", "DEFINITION_FUNCTION", 1, 5,
             "def _ensure_loaded():"),
        ])

    def test_prefers_exact_name_over_substring_superset(self):
        from squackit.workflows import investigate
        text = investigate(self._con(), None, "ensure_loaded",
                           file_pattern="**/*.py")
        assert "ensure_loaded" in text
        # the substring-superset symbol must be excluded
        assert "_ensure_loaded" not in text
        assert "vendored/cli.py" not in text

    def test_falls_back_to_substring_when_no_exact_match(self):
        from squackit.workflows import investigate
        # No symbol is named exactly "ensure"; both contain it, so the
        # forgiving substring lookup should still surface them.
        text = investigate(self._con(), None, "ensure",
                           file_pattern="**/*.py")
        assert "ensure_loaded" in text
        assert "_ensure_loaded" in text


# ── Integration tests: review ──────────────────────────────────────


@requires_fastmcp
class TestReview:
    """Test the review compound tool."""

    @pytest.fixture(scope="class")
    def text(self, mcp):
        return _text(_run_async(mcp.call_tool("review", {})))

    def test_returns_non_empty(self, text):
        assert len(text) > 0

    def test_contains_changed_files_section(self, text):
        assert "Changed Files" in text

    def test_contains_changed_functions_section(self, text):
        assert "Changed Functions" in text

    def test_contains_diff_section(self, text):
        assert "Diff" in text

    def test_tool_is_registered(self, mcp):
        assert "review" in _tool_names(mcp)


# ── Integration tests: search ──────────────────────────────────────


@requires_fastmcp
class TestSearch:
    """Test the search compound tool."""

    @pytest.fixture(scope="class")
    def text(self, mcp):
        return _text(_run_async(mcp.call_tool("search", {
            "query": "create_server",
        })))

    def test_returns_non_empty(self, text):
        assert len(text) > 0

    def test_contains_definitions_section(self, text):
        assert "Definitions" in text

    def test_contains_call_sites_section(self, text):
        assert "Call Sites" in text

    def test_contains_documentation_section(self, text):
        assert "Documentation" in text

    def test_finds_search_term(self, text):
        assert "create_server" in text

    def test_no_results_returns_structured_output(self, mcp):
        text = _text(_run_async(mcp.call_tool("search", {
            "query": "xyznonexistent999",
        })))
        assert len(text) > 0
        assert "Search" in text

    def test_tool_is_registered(self, mcp):
        assert "search" in _tool_names(mcp)


# ── Graceful degradation tests ─────────────────────────────────────


@requires_fastmcp
class TestGracefulDegradation:
    """Test that compound tools work with partial module sets."""

    @pytest.fixture(scope="class")
    def partial_mcp(self):
        """Server with only source + code modules (no git, no docs)."""
        from squackit.server import create_server
        return create_server(root=PROJECT_ROOT, init=False,
                             modules=["source", "code"])

    def test_explore_without_git_or_docs(self, partial_mcp):
        """explore returns partial briefing when git/docs unavailable."""
        text = _text(_run_async(partial_mcp.call_tool("explore", {})))
        assert "Languages" in text
        # Should still have section headings even if content failed
        assert "Explore" in text

    def test_search_without_conversations(self, partial_mcp):
        """search skips conversations section gracefully."""
        text = _text(_run_async(partial_mcp.call_tool("search", {
            "query": "test",
        })))
        assert "Search" in text
        assert "Definitions" in text
