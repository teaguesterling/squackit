"""Tests for squackit CLI tool subcommands."""

import json
from click.testing import CliRunner
from squackit.cli import cli


runner = CliRunner()


class TestToolList:

    def test_tool_list_shows_tools(self):
        result = runner.invoke(cli, ["tool", "list"])
        assert result.exit_code == 0, result.output
        assert "find_definitions" in result.output

    def test_tool_list_json(self):
        result = runner.invoke(cli, ["--json", "tool", "list"])
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        names = [t["name"] for t in parsed]
        assert "find_definitions" in names

    def test_tool_alias_t(self):
        result = runner.invoke(cli, ["t", "list"])
        assert result.exit_code == 0, result.output
        assert "find_definitions" in result.output


class TestToolNameResolution:

    def test_underscore(self):
        result = runner.invoke(cli, ["tool", "find_definitions", "--help"])
        assert result.exit_code == 0, result.output

    def test_kebab(self):
        result = runner.invoke(cli, ["tool", "find-definitions", "--help"])
        assert result.exit_code == 0, result.output

    def test_camel(self):
        result = runner.invoke(cli, ["tool", "FindDefinitions", "--help"])
        assert result.exit_code == 0, result.output

    def test_unknown_tool(self):
        result = runner.invoke(cli, ["tool", "nonexistent_tool"])
        assert result.exit_code != 0
