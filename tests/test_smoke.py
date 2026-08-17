"""Package smoke tests — imports only, no behavior."""


def test_import_squackit():
    import squackit
    assert squackit.__version__


def test_version_matches_the_installed_distribution():
    """Pin the exported version to the distribution, not to a literal.

    Asserting a hardcoded string here is what let `__version__` drift four
    releases behind pyproject.toml: bumping the release left the module and
    this test agreeing with each other and with nothing else. See #2 and #15.
    """
    from importlib.metadata import PackageNotFoundError, version
    import squackit
    try:
        expected = version("squackit")
    except PackageNotFoundError:
        expected = "0.0.0.dev0"
    assert squackit.__version__ == expected


def test_fledgling_available():
    """squackit's runtime depends on fledgling — verify it's importable."""
    import fledgling
    assert hasattr(fledgling, "connect")


def test_entry_point_importable():
    """The `squackit` CLI entry point must resolve to a callable."""
    from squackit.cli import cli
    assert callable(cli)


def test_server_create_importable():
    """create_server must remain importable for programmatic use."""
    from squackit.server import create_server
    assert callable(create_server)


def test_cli_script_installed():
    """pyproject.toml's [project.scripts] should install a `squackit` script."""
    import shutil
    assert shutil.which("squackit") is not None, \
        "squackit CLI script not on PATH — re-run `pip install -e .`"


def test_pluckit_available():
    """squackit's runtime depends on pluckit — verify it's importable."""
    import pluckit
    assert hasattr(pluckit, "Plucker")
