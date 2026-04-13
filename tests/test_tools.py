# tests/test_tools.py
"""Tests for squackit.tools -- pluckit-backed tool executors."""

import pytest
from squackit.tools import (
    PLUCKIT_TOOLS,
    view_executor,
    find_executor,
    find_names_executor,
    complexity_executor,
)


class TestViewExecutor:

    def test_returns_view_object(self):
        from pluckit.plugins.viewer import View
        result = view_executor(source="squackit/**/*.py", selector=".fn")
        assert isinstance(result, View)

    def test_view_has_markdown(self):
        result = view_executor(source="squackit/cli.py", selector=".fn#cli")
        assert "def cli" in result.markdown

    def test_view_has_blocks(self):
        result = view_executor(source="squackit/**/*.py", selector=".fn")
        assert len(result.blocks) > 0


class TestFindExecutor:

    def test_returns_relation(self):
        result = find_executor(source="squackit/**/*.py", selector=".fn")
        assert hasattr(result, "columns")
        assert hasattr(result, "fetchall")

    def test_relation_has_expected_columns(self):
        result = find_executor(source="squackit/**/*.py", selector=".fn")
        assert "name" in result.columns
        assert "file_path" in result.columns
        assert "start_line" in result.columns

    def test_finds_known_function(self):
        result = find_executor(source="squackit/cli.py", selector=".fn#cli")
        rows = result.fetchall()
        assert len(rows) >= 1


class TestFindNamesExecutor:

    def test_returns_list_of_strings(self):
        result = find_names_executor(source="squackit/**/*.py", selector=".fn")
        assert isinstance(result, list)
        assert all(isinstance(n, str) for n in result)

    def test_finds_known_function(self):
        result = find_names_executor(source="squackit/cli.py", selector=".fn")
        assert "cli" in result


class TestComplexityExecutor:

    def test_returns_relation(self):
        result = complexity_executor(source="squackit/**/*.py", selector=".fn")
        assert hasattr(result, "columns")
        assert "complexity" in result.columns

    def test_ordered_by_complexity_desc(self):
        result = complexity_executor(source="squackit/**/*.py", selector=".fn")
        rows = result.fetchall()
        cx_idx = result.columns.index("complexity")
        complexities = [r[cx_idx] for r in rows]
        assert complexities == sorted(complexities, reverse=True)


class TestPluckitToolsList:

    def test_four_tools_defined(self):
        assert len(PLUCKIT_TOOLS) == 4

    def test_all_have_executors(self):
        for tp in PLUCKIT_TOOLS:
            assert tp.executor is not None

    def test_tool_names(self):
        names = {tp.name for tp in PLUCKIT_TOOLS}
        assert names == {"view", "find", "find_names", "complexity"}

    def test_all_require_source_and_selector(self):
        for tp in PLUCKIT_TOOLS:
            assert "source" in tp.required
            assert "selector" in tp.required
