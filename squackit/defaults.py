"""Smart project-aware defaults for fledgling tools.

Infers sensible default patterns (code globs, doc paths, git revisions)
from the project at server startup. Users can override via
.fledgling-python/config.toml. Explicit tool parameters always win.
"""

from __future__ import annotations

import logging
import subprocess
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection as Connection


@dataclass
class ProjectDefaults:
    """Inferred at server startup, cached for the session.

    Patterns are stored RELATIVE (``**/*.py``) because they are shown to
    users — prompts.py interpolates ``code_pattern`` into tool guidance,
    where an absolute corpus path is noise. Anything handed to DuckDB
    must instead go through the anchored accessors below.

    WHY ANCHORING IS MANDATORY: a fledgling connection is sandboxed by
    default (fledgling >= 0.13), which limits the filesystem allow-list to
    ``root``. DuckDB resolves a relative glob against the process CWD, not
    against ``root``. A server's CWD is never the corpus it serves, so an
    un-anchored default pattern lands outside the allow-list and the query
    fails with a permission error — which callers upstack turn into "no
    results". See tests/test_sandbox_anchoring.py.
    """

    code_pattern: str = "**/*"
    doc_pattern: str = "**/*.md"
    main_branch: str = "main"
    from_rev: str = "HEAD~1"
    to_rev: str = "HEAD"
    languages: list[str] = field(default_factory=list)
    root: str | None = None

    def anchor(self, pattern: str | Path) -> str:
        """Resolve *pattern* against the project root.

        An absolute pattern is returned unchanged: a user who configured
        one meant it, and silently re-rooting it would be surprising.
        With no root known, the pattern is returned as-is, preserving the
        pre-sandbox behaviour for callers that construct defaults directly.
        """
        p = Path(pattern)
        if self.root is None or p.is_absolute():
            return str(pattern)
        return str(Path(self.root) / p)

    @property
    def code_glob(self) -> str:
        """``code_pattern`` anchored at root — use this for queries."""
        return self.anchor(self.code_pattern)

    @property
    def doc_glob(self) -> str:
        """``doc_pattern`` anchored at root — use this for queries."""
        return self.anchor(self.doc_pattern)

    def scoped_code_pattern(self, path: str | Path) -> str:
        """Scope the code pattern to a subdirectory path, anchored at root."""
        filename_glob = self.code_pattern.rsplit("/", 1)[-1]
        return self.anchor(Path(path) / "**" / filename_glob)

    def scoped_doc_pattern(self, path: str | Path) -> str:
        """Scope the doc pattern to a subdirectory path, anchored at root."""
        filename_glob = self.doc_pattern.rsplit("/", 1)[-1]
        return self.anchor(Path(path) / "**" / filename_glob)


def apply_defaults(
    defaults: ProjectDefaults,
    tool_name: str,
    kwargs: dict[str, object],
) -> dict[str, object]:
    """Substitute None params with smart defaults for a given tool.

    Returns a new dict — does not mutate the input.
    """
    mapping = TOOL_DEFAULTS.get(tool_name)
    if not mapping:
        return dict(kwargs)
    result = dict(kwargs)
    for param, attr_name in mapping.items():
        if result.get(param) is None:
            result[param] = getattr(defaults, attr_name)
        elif attr_name in _PATTERN_ATTRS:
            # An EXPLICIT pattern gets anchored too. A caller passing
            # `docs/**/*.md` means "docs under this project", but DuckDB
            # resolves it against the process cwd — outside the sandbox's
            # allow-list — so it raised a permission error instead of
            # returning rows. Relative means relative-to-root everywhere,
            # for defaults and explicit arguments alike. Absolute patterns
            # are passed through untouched by anchor().
            result[param] = defaults.anchor(result[param])
    return result


def load_config(root: str | Path) -> dict[str, str]:
    """Read defaults overrides from .fledgling-python/config.toml.

    Returns the [defaults] section as a flat dict, or {} if the file
    doesn't exist or has no [defaults] section.
    """
    config_path = Path(root) / ".fledgling-python" / "config.toml"
    if not config_path.is_file():
        return {}
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    return dict(data.get("defaults", {}))


# Attributes in TOOL_DEFAULTS that hold filesystem globs. Values for these
# params are root-anchored whether they came from the defaults or the caller.
_PATTERN_ATTRS = {"code_glob", "doc_glob"}

# Tool name → {param_name: defaults_attribute_name}
#
# These name the ANCHORED accessors (code_glob / doc_glob), not the raw
# pattern fields. A value substituted here goes straight to DuckDB, so it
# has to be resolvable from the sandbox's allow-list rather than from the
# process CWD. The raw code_pattern/doc_pattern fields remain for display.
TOOL_DEFAULTS: dict[str, dict[str, str]] = {
    "find_definitions":         {"file_pattern": "code_glob"},
    "find_in_ast":              {"file_pattern": "code_glob"},
    "code_structure":           {"file_pattern": "code_glob"},
    "complexity_hotspots":      {"file_pattern": "code_glob"},
    "changed_function_summary": {"file_pattern": "code_glob"},
    "doc_outline":              {"file_pattern": "doc_glob"},
    "file_changes":             {"from_rev": "from_rev", "to_rev": "to_rev"},
    "file_diff":                {"from_rev": "from_rev", "to_rev": "to_rev"},
    "structural_diff":          {"from_rev": "from_rev", "to_rev": "to_rev"},
}


# ── Language detection ──────────────────────────────────────────────

# Language name (as returned by project_overview) → file extensions.
# Hardcoded for now; will be replaced by sitting_duck's extension listing
# when available.
LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "Python": ["py", "pyi"],
    "JavaScript": ["js", "jsx", "mjs"],
    "TypeScript": ["ts", "tsx"],
    "Rust": ["rs"],
    "Go": ["go"],
    "Java": ["java"],
    "Ruby": ["rb"],
    "C": ["c"],
    "C++": ["cpp", "cc"],
    "C/C++": ["h", "hpp"],
    "SQL": ["sql"],
    "Shell": ["sh", "bash", "zsh"],
    "Kotlin": ["kt", "kts"],
    "Swift": ["swift"],
    "Dart": ["dart"],
    "PHP": ["php"],
    "Lua": ["lua"],
    "Zig": ["zig"],
    "R": ["r", "R"],
    "C#": ["cs"],
    "HCL": ["hcl", "tf"],
}

# Directories to check for docs, in priority order.
_DOC_DIRS = ["docs", "documentation", "doc", "wiki"]


def _code_glob(extensions: list[str]) -> str:
    """Build a glob pattern from a list of extensions.

    Uses only the primary (first) extension because DuckDB's glob()
    does not support brace expansion (e.g. ``**/*.{py,pyi}``).
    """
    return f"**/*.{extensions[0]}"


def _find_doc_dir(con: Connection, root: str | Path) -> str | None:
    """Check for common doc directories under `root` using list_files.

    Uses an absolute glob (``{root}/{d}/*``) so the probe doesn't depend
    on the connection's ``session_root`` matching the caller's intended
    project root. The previous relative-pattern form silently failed when
    ``session_root`` and the ``root`` parameter diverged, causing
    doc_pattern to fall back to ``**/*.md``.
    """
    root_path = Path(root)
    for d in _DOC_DIRS:
        try:
            pattern = str(root_path / d / "*")
            rows = con.list_files(pattern).fetchall()
            if rows:
                return d
        except Exception:
            log.debug("doc dir probe failed for %s", d, exc_info=True)
            continue
    return None


def _infer_main_branch(root: str | Path) -> str:
    """Detect the default branch from git remote HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
            capture_output=True, text=True, cwd=str(Path(root)), timeout=5,
        )
        if result.returncode == 0:
            # Output is "origin/main" or "origin/master" — strip prefix
            branch = result.stdout.strip().removeprefix("origin/")
            if branch:
                return branch
    except Exception:
        log.debug("git main branch detection failed", exc_info=True)
    return "main"


def infer_defaults(
    con: Connection,
    overrides: dict[str, str] | None = None,
    root: str | Path | None = None,
) -> ProjectDefaults:
    """Analyze the project and build smart defaults.

    Args:
        con: A fledgling Connection to the project.
        overrides: Values from config file that override inference.
        root: Project root for git operations. Defaults to cwd.

    Returns:
        ProjectDefaults with inferred + overridden values.
    """
    overrides = overrides or {}

    # ── Code pattern ────────────────────────────────────────────
    code_pattern = "**/*"
    languages: list[str] = []
    try:
        rows = con.project_overview().fetchall()
        # rows are (language, extension, file_count) ordered by count DESC
        if rows:
            # Group by language, sum file counts
            lang_counts: dict[str, int] = {}
            for lang, _ext, count in rows:
                lang_counts[lang] = lang_counts.get(lang, 0) + count
            languages = sorted(lang_counts.keys())
            # Find the top language that we have extension mappings for
            ranked = sorted(lang_counts, key=lang_counts.get, reverse=True)  # type: ignore[arg-type]
            for lang in ranked:
                if lang in LANGUAGE_EXTENSIONS:
                    code_pattern = _code_glob(LANGUAGE_EXTENSIONS[lang])
                    break
    except Exception:
        log.debug("project_overview inference failed", exc_info=True)

    # ── Doc pattern ─────────────────────────────────────────────
    doc_dir = _find_doc_dir(con, root or ".")
    doc_pattern = str(Path(doc_dir) / "**" / "*.md") if doc_dir else "**/*.md"

    # ── Main branch ─────────────────────────────────────────────
    main_branch = _infer_main_branch(root or ".")

    # ── Build defaults, apply overrides ─────────────────────────
    defaults = ProjectDefaults(
        code_pattern=code_pattern,
        doc_pattern=doc_pattern,
        main_branch=main_branch,
        languages=languages,
        root=str(root) if root is not None else None,
    )

    # Only real dataclass fields are settable. code_glob/doc_glob are
    # read-only properties, so a config file naming one would otherwise
    # raise AttributeError at startup instead of being ignored.
    settable = {f.name for f in fields(defaults)}
    for key, value in overrides.items():
        if key in settable:
            setattr(defaults, key, value)
        else:
            log.warning("ignoring unknown defaults override %r", key)

    return defaults
