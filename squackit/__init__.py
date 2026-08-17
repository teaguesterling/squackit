"""squackit: Semi-QUalified Agent Companion Kit — the stateful intelligence + MCP server layer for fledgling-equipped agents."""

from importlib.metadata import PackageNotFoundError, version as _dist_version

# Derived, never written by hand. The literal that used to live here read
# "0.4.1" while the installed distribution was 0.8.2 — four releases stale, and
# immune to --force-reinstall because it was not derived from anything. Someone
# debugging an unrelated problem read it, concluded they had a mixed install,
# and went looking for a packaging fault that did not exist. A version string
# that lies makes a healthy install look broken, which is the most expensive
# direction to send a reader.
try:
    __version__ = _dist_version("squackit")
except PackageNotFoundError:  # running from a source tree with no install
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
