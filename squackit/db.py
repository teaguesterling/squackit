"""DuckDB connection for squackit.

Thin wrapper over pluckit's Plucker that returns a fledgling-enabled
connection proxy with auto-generated macro wrappers.
"""

from pluckit import Plucker


def create_connection(**kwargs):
    """Create a fledgling-enabled DuckDB connection via pluckit.

    Accepts the same kwargs as :class:`pluckit.Plucker` (``repo``,
    ``profile``, ``modules``, ``init``). Returns the fledgling Connection
    proxy — the same object squackit's server.py uses as ``con``.
    """
    return Plucker(**kwargs).connection
