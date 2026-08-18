"""Default file patterns must be anchored at the project root.

WHY THIS FILE EXISTS
--------------------
fledgling 0.13.0 added ``sandbox: bool = True`` to ``connect()``. A
sandboxed connection restricts DuckDB's filesystem allow-list to the
``root`` it was given. squackit's inferred defaults were CWD-relative
(``**/*.py``), and DuckDB resolves a relative glob against the process
CWD — not against ``root``. Whenever CWD and root diverge (every server
deployment: the launcher's CWD is not the corpus), every default-pattern
query raised::

    Permission Error: Cannot access file "**/*.py"
                      - file system operations are disabled by configuration

...which ``investigate`` caught and reported as::

    No definition found for 'parse_config'. Try a broader pattern or check spelling.

So the tool answered "that symbol does not exist" about a symbol that did
exist, for every symbol, while the server reported all its tools healthy.
A missing-result message is indistinguishable from an empty corpus, which
is exactly why this needs a test rather than a comment.

``_find_doc_dir`` in defaults.py already carries a fix for the identical
bug ("the previous relative-pattern form silently failed when session_root
and the root parameter diverged"). This generalises that fix to the code
and doc patterns.

The regression tests below run the server with CWD deliberately OUTSIDE
root. Running them from inside root passes even with the bug, because
then the relative pattern happens to resolve to the right place.
"""

import asyncio
import os
import subprocess

import pytest

from squackit.defaults import ProjectDefaults, apply_defaults

try:
    import fastmcp  # noqa: F401
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False

requires_fastmcp = pytest.mark.skipif(
    not HAS_FASTMCP, reason="fastmcp not installed"
)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Unit tests: anchoring ───────────────────────────────────────────


class TestAnchoring:
    """ProjectDefaults exposes root-anchored globs for filesystem use."""

    def test_code_glob_is_anchored_at_root(self):
        d = ProjectDefaults(code_pattern="**/*.py", root="/srv/code/repo")
        assert d.code_glob == "/srv/code/repo/**/*.py"

    def test_doc_glob_is_anchored_at_root(self):
        d = ProjectDefaults(doc_pattern="docs/**/*.md", root="/srv/code/repo")
        assert d.doc_glob == "/srv/code/repo/docs/**/*.md"

    def test_absolute_pattern_is_left_alone(self):
        """A user who configured an absolute pattern meant it."""
        d = ProjectDefaults(code_pattern="/elsewhere/**/*.py", root="/srv/code")
        assert d.code_glob == "/elsewhere/**/*.py"

    def test_without_root_the_pattern_is_unchanged(self):
        """Back-compat: no root known, no anchoring, old behaviour."""
        d = ProjectDefaults(code_pattern="**/*.py")
        assert d.code_glob == "**/*.py"

    def test_raw_pattern_stays_relative_for_display(self):
        """prompts.py interpolates code_pattern into user-facing text; an
        absolute path there is noise, so the raw field must not change."""
        d = ProjectDefaults(code_pattern="**/*.py", root="/srv/code/repo")
        assert d.code_pattern == "**/*.py"

    def test_scoped_pattern_is_anchored(self):
        d = ProjectDefaults(code_pattern="**/*.py", root="/srv/code/repo")
        assert d.scoped_code_pattern("src") == "/srv/code/repo/src/**/*.py"

    def test_scoped_pattern_absolute_path_is_left_alone(self):
        d = ProjectDefaults(code_pattern="**/*.py", root="/srv/code/repo")
        assert d.scoped_code_pattern("/tmp/x") == "/tmp/x/**/*.py"

    def test_scoped_doc_pattern_is_anchored(self):
        d = ProjectDefaults(root="/srv/code/repo")
        assert d.scoped_doc_pattern("src") == "/srv/code/repo/src/**/*.md"


class TestExplicitPatternsAreAnchoredToo:
    """A caller-supplied relative glob means relative to the project."""

    def _defaults(self):
        return ProjectDefaults(
            code_pattern="**/*.py", doc_pattern="**/*.md", root="/srv/code/repo")

    def test_explicit_relative_code_pattern_is_anchored(self):
        out = apply_defaults(
            self._defaults(), "find_definitions", {"file_pattern": "src/**/*.py"})
        assert out["file_pattern"] == "/srv/code/repo/src/**/*.py"

    def test_explicit_relative_doc_pattern_is_anchored(self):
        out = apply_defaults(
            self._defaults(), "doc_outline", {"file_pattern": "docs/**/*.md"})
        assert out["file_pattern"] == "/srv/code/repo/docs/**/*.md"

    def test_explicit_absolute_pattern_is_untouched(self):
        out = apply_defaults(
            self._defaults(), "find_definitions", {"file_pattern": "/other/**/*.py"})
        assert out["file_pattern"] == "/other/**/*.py"

    def test_omitted_pattern_still_gets_the_anchored_default(self):
        out = apply_defaults(
            self._defaults(), "find_definitions", {"file_pattern": None})
        assert out["file_pattern"] == "/srv/code/repo/**/*.py"

    def test_non_pattern_params_are_not_anchored(self):
        """Git revisions are not paths — anchoring them would corrupt them."""
        out = apply_defaults(
            self._defaults(), "file_diff", {"from_rev": "HEAD~3", "to_rev": "HEAD"})
        assert out["from_rev"] == "HEAD~3"
        assert out["to_rev"] == "HEAD"


# ── Regression tests: the production shape ──────────────────────────


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """A real git repo with a uniquely-named function, used as root."""
    root = tmp_path_factory.mktemp("corpus") / "widget"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text(
        "def parse_widget_config(path):\n"
        "    '''Load the widget config.'''\n"
        "    return {}\n"
    )
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# Widget Guide\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@e", "-c", "user.name=t",
                    "commit", "-qm", "initial"], cwd=root, check=True)
    # A SECOND commit, so HEAD~1 resolves. `review` defaults to HEAD~1..HEAD,
    # and on a one-commit repo its git sections fail for that reason alone —
    # which renders as "(could not load)", exactly like the sandbox failure
    # this file is about. Without this the review test passes or fails for the
    # wrong reason.
    (root / "src" / "mod.py").write_text(
        "def parse_widget_config(path):\n"
        "    '''Load the widget config.'''\n"
        "    return {'version': 1}\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@e", "-c", "user.name=t",
                    "commit", "-qm", "second"], cwd=root, check=True)
    return root


@pytest.fixture
def outside_cwd(tmp_path, monkeypatch):
    """Put CWD somewhere that is NOT the project root.

    This is the whole point: a server's working directory is never the
    corpus it serves. With CWD == root the bug is invisible.
    """
    away = tmp_path / "elsewhere"
    away.mkdir()
    monkeypatch.chdir(away)
    return away


@requires_fastmcp
class TestServedFromForeignCwd:

    def _investigate(self, repo, name):
        from squackit.server import create_server
        mcp = create_server(root=str(repo), init=False)
        result = _run_async(mcp.call_tool("investigate", {"name": name}))
        return result.content[0].text

    def test_investigate_FINDS_a_definition_that_exists(self, repo, outside_cwd):
        """The regression: this returned 'No definition found' for every
        symbol when CWD diverged from root."""
        text = self._investigate(repo, "parse_widget_config")
        assert "No definition found" not in text, (
            "investigate reported a real symbol as missing — default pattern "
            "is almost certainly resolving against CWD instead of root"
        )
        assert "parse_widget_config" in text

    def test_a_genuinely_absent_symbol_still_reports_missing(self, repo, outside_cwd):
        """Guard against 'fixing' the above by never reporting misses."""
        text = self._investigate(repo, "no_such_symbol_anywhere")
        assert "No definition found" in text

    def test_defaults_are_inferred_from_root_not_cwd(self, repo, outside_cwd):
        """code_pattern is inferred by querying the project; from a foreign
        CWD a sandboxed connection saw nothing and fell back to '**/*'."""
        from squackit.server import create_server
        create_server(root=str(repo), init=False)  # smoke: must not raise

    def test_default_code_pattern_reaches_the_corpus(self, repo, outside_cwd):
        """A tool whose file_pattern comes from the inferred default, without
        investigate's try/except in the way — a failure here names the real
        cause instead of reporting an empty result."""
        from squackit.server import create_server
        mcp = create_server(root=str(repo), init=False)
        result = _run_async(mcp.call_tool("explore", {}))
        text = result.content[0].text
        assert "parse_widget_config" in text or "mod.py" in text, (
            f"explore saw no code under root:\n{text}"
        )

    def test_default_doc_pattern_reaches_the_corpus(self, repo, outside_cwd):
        """Same for doc_pattern — _find_doc_dir was fixed for this, but the
        pattern it produces was still relative."""
        from squackit.server import create_server
        mcp = create_server(root=str(repo), init=False)
        result = _run_async(mcp.call_tool("doc_outline", {}))
        assert "Widget Guide" in result.content[0].text or "guide.md" in result.content[0].text


# ── Workflow tools anchor explicit patterns too (0.8.4) ─────────────


@requires_fastmcp
class TestWorkflowToolsAnchorExplicitPatterns:
    """The compound tools never passed through `apply_defaults`.

    0.8.1 anchored caller-supplied relative patterns — but only on the macro
    tool wrapper in server.py. `investigate`, `review` and `search` take
    `file_pattern` as their own parameter and handed it to the macro unchanged,
    so an explicit relative glob still resolved against the process cwd and,
    under fledgling's sandbox, failed outright:

        investigate(name="parse_config", file_pattern="src/**/*.py")
        -> IOException: Failed to initialize file processing ... Permission

    Same deployment shape 0.8.1 was written for, reached through a different
    door. The CHANGELOG claim "caller-supplied relative patterns are anchored
    too" was true of the macro path only.
    """

    def _server(self, repo):
        from squackit.server import create_server
        return create_server(root=str(repo), init=False)

    def test_investigate_with_an_explicit_relative_pattern(self, repo, outside_cwd):
        mcp = self._server(repo)
        text = _run_async(mcp.call_tool(
            "investigate", {"name": "parse_widget_config",
                            "file_pattern": "src/**/*.py"})).content[0].text
        assert "Could not look up" not in text, (
            f"explicit relative pattern was not anchored:\n{text[:300]}")
        assert "parse_widget_config" in text

    def test_search_with_an_explicit_relative_pattern(self, repo, outside_cwd):
        mcp = self._server(repo)
        text = _run_async(mcp.call_tool(
            "search", {"query": "parse", "file_pattern": "src/**/*.py"})).content[0].text
        assert "could not load" not in text.lower(), (
            f"search section failed with an explicit relative pattern:\n{text[:400]}")

    def test_review_with_an_explicit_relative_pattern(self, repo, outside_cwd):
        mcp = self._server(repo)
        text = _run_async(mcp.call_tool(
            "review", {"file_pattern": "src/**/*.py"})).content[0].text
        assert "could not load" not in text.lower(), (
            f"review section failed with an explicit relative pattern:\n{text[:400]}")

    def test_an_explicit_absolute_pattern_is_still_honoured(self, repo, outside_cwd):
        """Anchoring must not re-root a path the caller gave in full."""
        mcp = self._server(repo)
        text = _run_async(mcp.call_tool(
            "investigate", {"name": "parse_widget_config",
                            "file_pattern": f"{repo}/src/**/*.py"})).content[0].text
        assert "parse_widget_config" in text


class TestAnchoringToleratesMissingDefaults:
    """An explicit pattern needs no defaults object.

    Regression: the 0.8.4 anchoring helper dereferenced `defaults` whenever a
    pattern was supplied, which broke callers that pass `defaults=None` to
    drive a workflow against a fake connection. The old code never touched
    defaults on that path — the caller had already said where to look.
    """

    def test_explicit_pattern_survives_a_none_defaults(self):
        from squackit.workflows import _anchored

        assert _anchored(None, "src/**/*.py") == "src/**/*.py"

    def test_none_pattern_with_none_defaults(self):
        from squackit.workflows import _anchored

        assert _anchored(None, None) is None

    def test_a_rootless_defaults_leaves_the_pattern_alone(self):
        from squackit.workflows import _anchored

        assert _anchored(ProjectDefaults(), "src/**/*.py") == "src/**/*.py"
