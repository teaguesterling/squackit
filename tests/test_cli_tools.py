"""Tests for squackit CLI tool subcommands."""

import json
from click.testing import CliRunner
from squackit.cli import cli


runner = CliRunner()


class TestToolList:

    def test_tool_list_shows_tools(self):
        result = runner.invoke(cli, ["tool", "list"])
        assert result.exit_code == 0, result.output
        # pluckit tools should appear; find_definitions is masked
        assert "view" in result.output
        assert "find" in result.output

    def test_tool_list_json(self):
        result = runner.invoke(cli, ["--json", "tool", "list"])
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        names = [t["name"] for t in parsed]
        assert "view" in names
        assert "find" in names

    def test_tool_alias_t(self):
        result = runner.invoke(cli, ["t", "list"])
        assert result.exit_code == 0, result.output
        assert "view" in result.output


class TestToolNameResolution:

    def test_underscore(self):
        result = runner.invoke(cli, ["tool", "read_source", "--help"])
        assert result.exit_code == 0, result.output

    def test_kebab(self):
        result = runner.invoke(cli, ["tool", "read-source", "--help"])
        assert result.exit_code == 0, result.output

    def test_camel(self):
        result = runner.invoke(cli, ["tool", "ReadSource", "--help"])
        assert result.exit_code == 0, result.output

    def test_unknown_tool(self):
        result = runner.invoke(cli, ["tool", "nonexistent_tool"])
        assert result.exit_code != 0


class TestPluckitToolsCli:

    def test_view_tool_exists(self):
        result = runner.invoke(cli, ["tool", "view", "--help"])
        assert result.exit_code == 0
        assert "selector" in result.output

    def test_find_tool_exists(self):
        result = runner.invoke(cli, ["tool", "find", "--help"])
        assert result.exit_code == 0
        assert "selector" in result.output

    def test_find_names_tool_exists(self):
        result = runner.invoke(cli, ["tool", "find_names", "--help"])
        assert result.exit_code == 0

    def test_complexity_tool_exists(self):
        result = runner.invoke(cli, ["tool", "complexity", "--help"])
        assert result.exit_code == 0

    def test_find_definitions_masked(self):
        """find_definitions should be masked when pluckit tools are present."""
        result = runner.invoke(cli, ["tool", "find_definitions", "--help"])
        assert result.exit_code != 0

    def test_view_runs(self):
        result = runner.invoke(cli, ["tool", "view", "squackit/cli.py", ".fn#cli"])
        assert result.exit_code == 0, result.output
        assert "def cli" in result.output

    def test_find_runs(self):
        result = runner.invoke(cli, ["tool", "find", "squackit/**/*.py", ".fn"])
        assert result.exit_code == 0, result.output

    def test_find_names_runs(self):
        result = runner.invoke(cli, ["tool", "find_names", "squackit/cli.py", ".fn"])
        assert result.exit_code == 0, result.output
        assert "cli" in result.output

    def test_find_json(self):
        result = runner.invoke(cli, ["--json", "tool", "find", "squackit/cli.py", ".fn"])
        assert result.exit_code == 0, result.output
        import json
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
