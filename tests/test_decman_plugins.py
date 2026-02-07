from decman.core.module import Module
from decman.plugins import run_methods_with_attribute


def mark(attr):
    attr.__flag__ = True
    return attr


def test_runs_marked_method_and_returns_value():
    class M(Module):
        @mark
        def foo(self):
            return 123

    m = M("m")
    assert run_methods_with_attribute(m, "__flag__") == [123]


def test_runs_marked_methods_and_returns_value():
    class M(Module):
        @mark
        def foo(self):
            return 123

        @mark
        def bar(self):
            return 321

    m = M("m")
    assert run_methods_with_attribute(m, "__flag__") == [321, 123]


def test_returns_none_if_no_method_has_attribute():
    class M(Module):
        def foo(self):
            return 1

    m = M("m")
    assert run_methods_with_attribute(m, "__flag__") == []
