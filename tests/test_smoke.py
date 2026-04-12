"""Package smoke tests — imports only, no behavior."""


def test_import_squawkit():
    import squawkit
    assert squawkit.__version__ == "0.1.0"


def test_fledgling_available():
    """squawkit's runtime depends on fledgling — verify it's importable."""
    import fledgling
    assert hasattr(fledgling, "connect")


def test_entry_point_importable():
    """The `squawkit` CLI entry point must resolve to a callable."""
    from squawkit.server import main
    assert callable(main)


def test_cli_script_installed():
    """pyproject.toml's [project.scripts] should install a `squawkit` script."""
    import shutil
    assert shutil.which("squawkit") is not None, \
        "squawkit CLI script not on PATH — re-run `pip install -e .`"


def test_pluckit_available():
    """squawkit's runtime depends on pluckit — verify it's importable."""
    import pluckit
    assert hasattr(pluckit, "Plucker")
