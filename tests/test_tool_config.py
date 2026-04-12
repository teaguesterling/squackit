"""Tests for squackit.tool_config — ToolPresentation and name resolution."""

from fledgling.tools import ToolInfo
from squackit.tool_config import normalize_tool_name, to_kebab, to_camel, ToolPresentation


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


class TestToolPresentation:

    def _make_info(self, **kwargs) -> ToolInfo:
        defaults = dict(macro_name="read_source", params=["file_path", "lines", "ctx", "match"])
        defaults.update(kwargs)
        return ToolInfo(**defaults)

    def test_name_delegates_to_macro_name(self):
        tp = ToolPresentation(info=self._make_info())
        assert tp.name == "read_source"

    def test_name_prefers_tool_name(self):
        tp = ToolPresentation(info=self._make_info(tool_name="ReadLines"))
        assert tp.name == "ReadLines"

    def test_name_prefers_alias_over_tool_name(self):
        tp = ToolPresentation(
            info=self._make_info(tool_name="ReadLines"),
            alias="read_source",
        )
        assert tp.name == "read_source"

    def test_required_from_info_required(self):
        tp = ToolPresentation(info=self._make_info(required=["file_path"]))
        assert tp.required == ["file_path"]
        assert tp.optional == ["lines", "ctx", "match"]

    def test_required_fallback_to_required_params(self):
        tp = ToolPresentation(info=self._make_info())
        # Catalog fallback: all params marked required
        assert tp.required == ["file_path", "lines", "ctx", "match"]

    def test_required_override(self):
        tp = ToolPresentation(
            info=self._make_info(),
            required_override=["file_path"],
        )
        assert tp.required == ["file_path"]
        assert tp.optional == ["lines", "ctx", "match"]

    def test_format_from_info(self):
        tp = ToolPresentation(info=self._make_info(format="text"))
        assert tp.format == "text"

    def test_format_default_table(self):
        tp = ToolPresentation(info=self._make_info())
        assert tp.format == "table"

    def test_format_override(self):
        tp = ToolPresentation(
            info=self._make_info(format="markdown"),
            format_override="text",
        )
        assert tp.format == "text"

    def test_description_from_info(self):
        tp = ToolPresentation(info=self._make_info(description="Read file lines."))
        assert tp.description == "Read file lines."

    def test_description_fallback(self):
        tp = ToolPresentation(info=self._make_info())
        assert "read_source" in tp.description

    def test_description_override(self):
        tp = ToolPresentation(
            info=self._make_info(description="Original."),
            description_override="Custom.",
        )
        assert tp.description == "Custom."

    def test_parameters_schema_delegates(self):
        schema = {"file_path": {"type": "string"}}
        tp = ToolPresentation(info=self._make_info(parameters_schema=schema))
        assert tp.parameters_schema == schema

    def test_numeric_params_from_schema(self):
        schema = {
            "file_path": {"type": "string"},
            "ctx": {"type": "integer"},
            "n": {"type": "integer"},
        }
        tp = ToolPresentation(info=self._make_info(
            params=["file_path", "ctx", "n"],
            parameters_schema=schema,
        ))
        assert tp.numeric_params == {"ctx", "n"}

    def test_numeric_params_without_schema(self):
        tp = ToolPresentation(info=self._make_info())
        assert "ctx" in tp.numeric_params
