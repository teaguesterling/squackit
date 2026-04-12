"""Tests for squackit.tool_config — ToolPresentation and name resolution."""

from squackit.tool_config import normalize_tool_name, to_kebab, to_camel


class TestNameNormalization:
    def test_underscore_passthrough(self):
        assert normalize_tool_name("find_definitions") == "find_definitions"

    def test_kebab_to_underscore(self):
        assert normalize_tool_name("find-definitions") == "find_definitions"

    def test_camel_to_underscore(self):
        assert normalize_tool_name("FindDefinitions") == "find_definitions"

    def test_single_word(self):
        assert normalize_tool_name("help") == "help"

    def test_camel_single_word(self):
        assert normalize_tool_name("Help") == "help"

    def test_consecutive_caps(self):
        assert normalize_tool_name("ASTSelect") == "ast_select"


class TestToKebab:
    def test_simple(self):
        assert to_kebab("find_definitions") == "find-definitions"

    def test_single_word(self):
        assert to_kebab("help") == "help"


class TestToCamel:
    def test_simple(self):
        assert to_camel("find_definitions") == "FindDefinitions"

    def test_single_word(self):
        assert to_camel("help") == "Help"

    def test_three_parts(self):
        assert to_camel("read_doc_section") == "ReadDocSection"
