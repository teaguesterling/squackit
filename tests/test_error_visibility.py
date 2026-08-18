"""A failure must not be representable as an ordinary result.

Three places used to violate that, each in a different way:

* ``investigate`` caught every query exception and rendered it with the same
  sentence it uses for a genuine miss — so a permission error, a binder error
  and "that symbol isn't here" were indistinguishable, and the advice offered
  ("try a broader pattern") actively misdirected. This is not hypothetical: it
  is exactly how the 0.8.1 sandbox bug presented, for hours, while the server
  reported every tool healthy.
* ``collect_pluckin_tools`` dropped a raising pluckin's tools with a bare
  ``pass`` under a comment claiming the error would be surfaced elsewhere.
  Nothing surfaced it. A silently shorter tool surface is worse than a silently
  empty result — an empty result prompts "did that work?", a shorter tool list
  reads as a different, reasonable version of the product.
* Auto-generated macro descriptions were a bare signature, so a SQL macro named
  ``ast_replace`` — which computes patched source and writes nothing, because a
  SQL macro *cannot* write — read as a mutation to any caller.

See issues #14 and #16.
"""

import logging

import pytest

from squackit.defaults import ProjectDefaults
from squackit.tool_config import ToolPresentation
from squackit.tools import collect_pluckin_tools
from squackit.workflows import investigate


# ── investigate: a failed query is not a miss ───────────────────────


class _Rel:
    def __init__(self, rows, cols):
        self._rows, self.columns = rows, cols

    def fetchall(self):
        return self._rows


class _ConRaises:
    """A connection whose lookup fails the way a sandboxed one does."""

    def __init__(self, exc):
        self._exc = exc

    def find_definitions(self, **kw):
        raise self._exc


class _ConEmpty:
    """A connection that works and genuinely has no match."""

    def find_definitions(self, **kw):
        return _Rel([], ["file_path", "name", "kind",
                         "start_line", "end_line", "signature"])


@pytest.fixture
def defaults(tmp_path):
    return ProjectDefaults(code_pattern="**/*.py", root=str(tmp_path))


class TestInvestigateDistinguishesFailureFromMiss:

    def test_genuine_miss_keeps_the_helpful_message(self, defaults):
        """The friendly wording is right when it IS a miss — keep it."""
        out = investigate(_ConEmpty(), defaults, "nonexistent_symbol")
        assert "No definition found" in out
        assert "nonexistent_symbol" in out

    def test_query_failure_does_NOT_claim_the_symbol_is_absent(self, defaults):
        out = investigate(_ConRaises(RuntimeError("boom")), defaults, "parse_config")
        assert "No definition found" not in out, (
            "a failed lookup was reported as a confirmed absence"
        )

    def test_query_failure_says_it_failed(self, defaults):
        out = investigate(_ConRaises(RuntimeError("boom")), defaults, "parse_config")
        assert "could not" in out.lower() or "failed" in out.lower()

    def test_query_failure_surfaces_the_underlying_error(self, defaults):
        """The 0.8.1 bug was diagnosable only from this text."""
        exc = RuntimeError(
            'Permission Error: Cannot access file "**/*.py" '
            "- file system operations are disabled by configuration"
        )
        out = investigate(_ConRaises(exc), defaults, "parse_config")
        assert "Permission Error" in out, out

    def test_query_failure_does_NOT_advise_broadening_the_pattern(self, defaults):
        """That advice sends the reader at the wrong thing entirely."""
        out = investigate(_ConRaises(RuntimeError("boom")), defaults, "parse_config")
        assert "broader pattern" not in out


# ── collect_pluckin_tools: a dropped pluckin is logged ───────────────


class _Pluckin:
    def __init__(self, tools=None, exc=None):
        self._tools, self._exc = tools or [], exc

    def squackit_tools(self):
        if self._exc:
            raise self._exc
        return self._tools


class _Plucker:
    def __init__(self, pluckins):
        self.pluckins = pluckins


class TestPluckinFailuresAreVisible:

    def test_a_raising_pluckin_does_not_break_the_registry(self):
        """The guard itself is correct and stays."""
        good = _Pluckin(tools=["t1", "t2"])
        bad = _Pluckin(exc=RuntimeError("plugin exploded"))
        assert collect_pluckin_tools(_Plucker([bad, good])) == ["t1", "t2"]

    def test_a_raising_pluckin_is_LOGGED(self, caplog):
        bad = _Pluckin(exc=RuntimeError("plugin exploded"))
        with caplog.at_level(logging.WARNING, logger="squackit.tools"):
            collect_pluckin_tools(_Plucker([bad]))
        assert caplog.records, "a pluckin's tools vanished with no log record"

    def test_the_log_names_the_pluckin_and_the_error(self, caplog):
        bad = _Pluckin(exc=RuntimeError("plugin exploded"))
        with caplog.at_level(logging.WARNING, logger="squackit.tools"):
            collect_pluckin_tools(_Plucker([bad]))
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "_Pluckin" in text, text
        assert "plugin exploded" in text, text

    def test_healthy_pluckins_log_nothing(self, caplog):
        with caplog.at_level(logging.WARNING, logger="squackit.tools"):
            collect_pluckin_tools(_Plucker([_Pluckin(tools=["t1"])]))
        assert not caplog.records


# ── generated descriptions state their semantics ─────────────────────


class _Info:
    """Stand-in for fledgling's ToolInfo carrying no description of its own.

    ToolPresentation derives `name` and `params` from the info object, so the
    stub has to supply macro_name/params rather than the presentation taking
    them directly.
    """

    def __init__(self, macro_name, params, description=None):
        self.macro_name = macro_name
        self.tool_name = None
        self.params = list(params)
        self.description = description
        self.required = None
        self.required_params = []
        self.format = None
        self.parameters_schema = None


def _presentation(name, params):
    return ToolPresentation(info=_Info(name, params))


class TestMutationNamedMacrosSayTheyDoNotMutate:

    def test_ast_replace_states_it_does_not_modify(self):
        d = _presentation("ast_replace", ["source", "selector", "new_text"])
        assert "does not modify" in d.description.lower(), d.description

    def test_ast_patch_states_it_does_not_modify(self):
        d = _presentation("ast_patch", ["edits", "files"])
        assert "does not modify" in d.description.lower(), d.description

    def test_the_signature_is_still_there(self):
        d = _presentation("ast_replace", ["source", "selector", "new_text"])
        assert "ast_replace(source, selector, new_text)" in d.description

    def test_read_only_macros_are_NOT_cluttered(self):
        """A disclaimer on all 90 macros is context every agent pays for."""
        d = _presentation("find_definitions", ["file_pattern", "name_pattern"])
        assert "does not modify" not in d.description.lower()

    def test_a_real_description_still_wins(self):
        info = _Info("ast_replace", ["source"], description="The macro's own words.")
        assert ToolPresentation(info=info).description == "The macro's own words."

    def test_an_override_still_wins(self):
        d = ToolPresentation(info=_Info("ast_replace", ["source"]),
                             description_override="Overridden.")
        assert d.description == "Overridden."


# ── Briefing sections name their failure (#2 from the 0.8.3 review) ──


class TestSectionFailuresAreNamed:
    """`_section` wraps every part of explore/review/search/investigate.

    It caught everything, logged at DEBUG (invisible at normal levels) and
    rendered "(could not load)" — a string that cannot be told apart from a
    section that legitimately has nothing, and which names no cause. 0.8.3
    fixed exactly this shape in investigate's primary lookup but never reached
    the sibling sections, so the same permission error that motivated 0.8.1
    still arrived as undifferentiated text in three of the four compound tools.
    """

    def test_a_failing_section_still_reports_could_not_load(self):
        """Keep the recognisable phrase — callers and tests match on it."""
        from squackit.workflows import _section

        heading, content = _section("Diffs", lambda: (_ for _ in ()).throw(
            RuntimeError("boom")))
        assert heading == "Diffs"
        assert "could not load" in content.lower()

    def test_a_failing_section_names_the_error(self):
        from squackit.workflows import _section

        _heading, content = _section("Diffs", lambda: (_ for _ in ()).throw(
            RuntimeError("permission denied on **/*.py")))
        assert "RuntimeError" in content, content
        assert "permission denied" in content, content

    def test_an_empty_section_is_distinguishable_from_a_failed_one(self):
        from squackit.workflows import _section

        _h, empty = _section("Docs", lambda: "")
        _h2, failed = _section("Docs", lambda: (_ for _ in ()).throw(
            RuntimeError("boom")))
        assert empty != failed
        assert "no data" in empty.lower()

    def test_a_very_long_error_is_capped_visibly(self):
        """DuckDB errors run to hundreds of characters; a briefing is prose."""
        from squackit.workflows import _section

        _h, content = _section("Diffs", lambda: (_ for _ in ()).throw(
            RuntimeError("x" * 4000)))
        assert len(content) < 400, len(content)
        assert "…" in content or "..." in content, content

    def test_a_working_section_is_untouched(self):
        from squackit.workflows import _section

        assert _section("Docs", lambda: "| a | b |") == ("Docs", "| a | b |")
