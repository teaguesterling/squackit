"""Tests for squackit.tool_config — ToolPresentation and name resolution."""

from fledgling.tools import ToolInfo
from squackit.tool_config import (
    normalize_tool_name, to_kebab, to_camel, ToolPresentation,
    build_tool_registry, SKIP, OVERRIDES, MASKED_BY_PLUCKIT,
)


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


class TestBuildToolRegistry:

    def test_builds_from_tools_iterable(self):
        tools = [
            ToolInfo(macro_name="find_definitions", params=["file_pattern", "name_pattern"]),
            ToolInfo(macro_name="list_files", params=["pattern", "commit"]),
        ]
        registry = build_tool_registry(tools)
        assert "find_definitions" in registry
        assert "list_files" in registry
        assert len(registry) == 2

    def test_skips_macros_in_skip_set(self):
        tools = [
            ToolInfo(macro_name="find_definitions", params=["file_pattern"]),
            ToolInfo(macro_name="ast_ancestors", params=["ast_table", "child_node_id"]),
        ]
        registry = build_tool_registry(tools)
        assert "find_definitions" in registry
        assert "ast_ancestors" not in registry

    def test_applies_overrides(self):
        tools = [
            ToolInfo(macro_name="pss_render", params=["source", "selector"]),
        ]
        registry = build_tool_registry(tools)
        assert "select_code" in registry
        assert "pss_render" not in registry
        assert registry["select_code"].macro_name == "pss_render"

    def test_override_format(self):
        tools = [
            ToolInfo(macro_name="read_source", params=["file_path", "lines", "ctx", "match"]),
        ]
        registry = build_tool_registry(tools)
        assert registry["read_source"].format == "text"

    def test_override_required(self):
        tools = [
            ToolInfo(macro_name="read_source", params=["file_path", "lines", "ctx", "match"]),
        ]
        registry = build_tool_registry(tools)
        assert registry["read_source"].required == ["file_path"]

    def test_skip_set_covers_known_internal_macros(self):
        assert "ast_ancestors" in SKIP
        assert "load_conversations" in SKIP
        assert "ast_select" in SKIP

    def test_overrides_has_key_tools(self):
        assert "pss_render" in OVERRIDES
        assert "read_source" in OVERRIDES


class TestExecutorField:

    def test_executor_default_none(self):
        info = ToolInfo(macro_name="test", params=["a"])
        tp = ToolPresentation(info=info)
        assert tp.executor is None

    def test_executor_set(self):
        def my_exec(**kwargs):
            return kwargs
        info = ToolInfo(macro_name="test", params=["a"])
        tp = ToolPresentation(info=info, executor=my_exec)
        assert tp.executor is my_exec


class TestExtraTools:

    def test_extra_tools_registered(self):
        def my_exec(**kwargs):
            return kwargs
        extra = [
            ToolPresentation(
                info=ToolInfo(macro_name="my_tool", params=["x"]),
                executor=my_exec,
            ),
        ]
        fledgling_tools = [
            ToolInfo(macro_name="list_files", params=["pattern"]),
        ]
        registry = build_tool_registry(fledgling_tools, extra_tools=extra)
        assert "my_tool" in registry
        assert "list_files" in registry

    def test_extra_tools_take_priority(self):
        def my_exec(**kwargs):
            return kwargs
        extra = [
            ToolPresentation(
                info=ToolInfo(macro_name="find_definitions", params=["source", "selector"]),
                executor=my_exec,
            ),
        ]
        fledgling_tools = [
            ToolInfo(macro_name="find_definitions", params=["file_pattern", "name_pattern"]),
        ]
        registry = build_tool_registry(fledgling_tools, extra_tools=extra)
        assert registry["find_definitions"].executor is my_exec

    def test_masked_by_pluckit(self):
        assert "pss_render" in MASKED_BY_PLUCKIT
        assert "find_definitions" in MASKED_BY_PLUCKIT
        assert "code_structure" in MASKED_BY_PLUCKIT
        assert "complexity_hotspots" in MASKED_BY_PLUCKIT

    def test_masked_tools_skipped_when_extra_present(self):
        def my_exec(**kwargs):
            return kwargs
        extra = [
            ToolPresentation(
                info=ToolInfo(macro_name="view", params=["source", "selector"]),
                executor=my_exec,
            ),
        ]
        fledgling_tools = [
            ToolInfo(macro_name="pss_render", params=["source", "selector"]),
            ToolInfo(macro_name="list_files", params=["pattern"]),
        ]
        registry = build_tool_registry(fledgling_tools, extra_tools=extra)
        assert "view" in registry
        assert "select_code" not in registry
        assert "list_files" in registry
