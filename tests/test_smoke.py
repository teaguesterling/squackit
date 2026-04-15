"""Package smoke tests — imports only, no behavior."""


def test_import_squackit():
    import squackit
    assert squackit.__version__ == "0.4.1"


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
