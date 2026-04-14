# tests/test_tools.py
"""Tests for squackit.tools -- pluckit-backed tool executors."""

import pytest
from squackit.tools import (
    PLUCKIT_TOOLS,
    view_executor,
    find_executor,
    find_names_executor,
    complexity_executor,
    pluck_executor,
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

    def test_five_tools_defined(self):
        assert len(PLUCKIT_TOOLS) == 5

    def test_all_have_executors(self):
        for tp in PLUCKIT_TOOLS:
            assert tp.executor is not None

    def test_tool_names(self):
        names = {tp.name for tp in PLUCKIT_TOOLS}
        assert names == {"view", "find", "find_names", "complexity", "pluck"}

    def test_selector_tools_require_source_and_selector(self):
        for tp in PLUCKIT_TOOLS:
            if tp.name == "pluck":
                continue
            assert "source" in tp.required
            assert "selector" in tp.required

    def test_pluck_requires_argv(self):
        pluck = next(tp for tp in PLUCKIT_TOOLS if tp.name == "pluck")
        assert "argv" in pluck.required


class TestPluckExecutor:

    def test_returns_json_string(self):
        import json
        result = pluck_executor(argv="squackit/cli.py find .fn names")
        parsed = json.loads(result)
        assert "chain" in parsed
        assert "type" in parsed
        assert "data" in parsed

    def test_find_names(self):
        import json
        result = pluck_executor(argv="squackit/cli.py find .fn names")
        parsed = json.loads(result)
        assert parsed["type"] == "names"
        assert isinstance(parsed["data"], list)
        assert "cli" in parsed["data"]

    def test_count(self):
        import json
        result = pluck_executor(argv="squackit/cli.py find .fn count")
        parsed = json.loads(result)
        assert parsed["type"] == "count"
        assert isinstance(parsed["data"], int)
        assert parsed["data"] > 0

    def test_view_with_plugin(self):
        import json
        result = pluck_executor(
            argv="--plugin AstViewer squackit/cli.py find .fn#cli view"
        )
        parsed = json.loads(result)
        assert parsed["type"] == "view"
        # data is a dict with blocks
        assert "blocks" in parsed["data"]

    def test_empty_argv_returns_error(self):
        import json
        result = pluck_executor(argv="")
        parsed = json.loads(result)
        assert "error" in parsed
