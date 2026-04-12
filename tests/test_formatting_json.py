"""Tests for JSON output formatting."""

import json
from squackit.formatting import format_json


class TestFormatJson:

    def test_basic_table(self):
        cols = ["name", "kind", "start_line"]
        rows = [("main", "function", 10), ("Foo", "class", 25)]
        output = format_json(cols, rows)
        parsed = json.loads(output)
        assert len(parsed) == 2
        assert parsed[0] == {"name": "main", "kind": "function", "start_line": 10}
        assert parsed[1] == {"name": "Foo", "kind": "class", "start_line": 25}

    def test_empty_rows(self):
        cols = ["name"]
        rows = []
        output = format_json(cols, rows)
        assert json.loads(output) == []

    def test_none_values(self):
        cols = ["name", "value"]
        rows = [("test", None)]
        output = format_json(cols, rows)
        parsed = json.loads(output)
        assert parsed[0] == {"name": "test", "value": None}

    def test_single_column_text(self):
        cols = ["content"]
        rows = [("line 1",), ("line 2",)]
        output = format_json(cols, rows)
        parsed = json.loads(output)
        assert parsed == [{"content": "line 1"}, {"content": "line 2"}]
