"""Fixture for the :has(.call#name) regression test.

Four top-level functions; exactly two call `_target`. Used to pin that
`:has(.call#_target)` applies the nested `#_target` filter rather than
dropping it and matching every function (sitting_duck #72 / squackit #8).
"""


def _target():
    return 1


def calls_target_once():
    return _target()


def calls_target_twice():
    a = _target()
    return a + _target()


def calls_other():
    return len([])
