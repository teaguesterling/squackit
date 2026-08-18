"""Tools can return structured data instead of rendered prose.

squackit's tools render for a human reader: tabular results become markdown
tables, line-oriented ones become newline-joined text. That is right for an
agent reading a briefing and close to useless to a program composing calls.

Measured by a session running local models against the suite through lackpy,
which generates one restricted-Python program per intent:

    0/24 correct while 17/24 called the correct tool

The models picked the right tool and misread the return shape. `len()` on
`find_names`' newline-joined string gives 67 (characters) where the answer is
8; on `find`'s markdown table it gives 2239. A wrong guess still validates,
still runs, and answers confidently.

The structure is not lost — it is discarded at the last step. The executors
already return DuckDB relations and View objects, and the CLI already has
`--json` using the same formatter. This exposes that over MCP.

## The shape

`as_json=True` returns ONE envelope for every tool:

    {"rows": [...], "columns": [...], "omitted": <int>}

Chosen deliberately over a bare array:

* it is the same shape for every tool, so a caller learns it once
* `omitted` makes truncation REPRESENTABLE. A bare array that had been cut
  would be indistinguishable from a complete one — silent truncation is the
  defect this suite has been chasing all week, and returning it in the
  programmatic path would be a poor joke.
* `columns` means a caller does not have to guess key names

The cost is that `len(result)` on the envelope is 3, not the row count — the
same trap that produced the 0/24. That is why the shape is stated in the tool
description rather than left to be inferred.
"""

import json

import pytest

from squackit.defaults import ProjectDefaults

try:
    import fastmcp  # noqa: F401
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False

requires_fastmcp = pytest.mark.skipif(
    not HAS_FASTMCP, reason="fastmcp not installed"
)

import asyncio
import subprocess


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """Eight functions, so a count is unambiguous."""
    root = tmp_path_factory.mktemp("structured") / "proj"
    (root / "src").mkdir(parents=True)
    body = "\n".join(f"def fn_{i}(a):\n    return {i}\n" for i in range(8))
    (root / "src" / "mod.py").write_text(body)
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# Guide\n\n## Section\n\ntext\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@e", "-c", "user.name=t",
                    "commit", "-qm", "initial"], cwd=root, check=True)
    # Absolute: a relative source roots at the process cwd by design (0.8.2),
    # which is not the served corpus. A caller addressing a served repo names
    # it in full, and that is the shape worth testing.
    global SRC
    SRC = str(root / "src" / "mod.py")
    return root


SRC = None  # set by the repo fixture: an ABSOLUTE source path.


@pytest.fixture
def mcp(repo):
    from squackit.server import create_server
    return create_server(root=str(repo), init=False)


def _call(mcp, tool, args):
    return _run_async(mcp.call_tool(tool, args)).content[0].text


@requires_fastmcp
class TestFindNamesJson:
    """The sharpest measured case: a count that was 67 instead of 8."""

    def test_default_is_unchanged(self, mcp):
        """Existing callers must see exactly what they saw before."""
        text = _call(mcp, "find_names", {"source": SRC,
                                         "selector": ".function"})
        assert not text.lstrip().startswith("{")
        assert "fn_0" in text

    def test_as_json_parses(self, mcp):
        payload = json.loads(_call(mcp, "find_names", {
            "source": SRC, "selector": ".function", "as_json": True}))
        assert isinstance(payload, dict)

    def test_len_of_rows_is_the_answer(self, mcp):
        """This is the number the models got wrong."""
        payload = json.loads(_call(mcp, "find_names", {
            "source": SRC, "selector": ".function", "as_json": True}))
        assert len(payload["rows"]) == 8, payload

    def test_rows_are_the_names_themselves(self, mcp):
        payload = json.loads(_call(mcp, "find_names", {
            "source": SRC, "selector": ".function", "as_json": True}))
        assert "fn_0" in payload["rows"]


@requires_fastmcp
class TestRelationToolsJson:

    def test_find_returns_rows_of_objects(self, mcp):
        payload = json.loads(_call(mcp, "find", {
            "source": SRC, "selector": ".function", "as_json": True}))
        assert len(payload["rows"]) == 8
        assert isinstance(payload["rows"][0], dict)

    def test_columns_are_declared(self, mcp):
        payload = json.loads(_call(mcp, "find", {
            "source": SRC, "selector": ".function", "as_json": True}))
        assert "name" in payload["columns"]
        assert set(payload["rows"][0]) <= set(payload["columns"])

    def test_a_macro_tool_also_supports_it(self, mcp):
        """Not just the pluckit tools — both wrappers."""
        payload = json.loads(_call(mcp, "doc_outline", {"as_json": True}))
        assert isinstance(payload["rows"], list)
        assert isinstance(payload["columns"], list)

    def test_default_markdown_is_unchanged(self, mcp):
        text = _call(mcp, "find", {"source": SRC,
                                   "selector": ".function"})
        assert text.lstrip().startswith("|")


@requires_fastmcp
class TestTruncationStaysVisible:
    """A cut array that looks complete is the defect, not the feature."""

    def test_omitted_is_reported(self, mcp):
        payload = json.loads(_call(mcp, "find", {
            "source": SRC, "selector": ".function",
            "max_results": 3, "as_json": True}))
        assert len(payload["rows"]) == 3
        assert payload["omitted"] == 5, payload

    def test_omitted_is_zero_when_complete(self, mcp):
        payload = json.loads(_call(mcp, "find", {
            "source": SRC, "selector": ".function", "as_json": True}))
        assert payload["omitted"] == 0

    def test_no_markdown_omission_line_leaks_into_json(self, mcp):
        """Appending '--- omitted N rows ---' to JSON would break parsing."""
        raw = _call(mcp, "find", {"source": SRC,
                                  "selector": ".function",
                                  "max_results": 3, "as_json": True})
        assert "---" not in raw
        json.loads(raw)  # must not raise


@requires_fastmcp
class TestEmptyAndErrorCases:

    def test_an_empty_result_is_an_empty_array_not_a_message(self, mcp):
        """`(no results)` is prose; a program needs [] it can iterate."""
        payload = json.loads(_call(mcp, "find_names", {
            "source": SRC, "selector": ".class", "as_json": True}))
        assert payload["rows"] == []
        assert payload["omitted"] == 0
