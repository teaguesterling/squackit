"""Package smoke tests — imports only, no behavior."""


def test_import_squawkit():
    import squawkit
    assert squawkit.__version__ == "0.1.0"


def test_fledgling_available():
    """squawkit's runtime depends on fledgling — verify it's importable."""
    import fledgling
    assert hasattr(fledgling, "connect")
