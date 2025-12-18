import stat
import subprocess
import sys
from pathlib import Path

import pytest

import decman.core.error as errors
import decman.core.module as module


def test_module_without_on_disable_is_accepted():
    class NoOnDisable(module.Module):
        def __init__(self):
            super().__init__("no_on_disable")

    m = NoOnDisable()
    assert m.name == "no_on_disable"


def test_on_disable_must_be_staticmethod():
    with pytest.raises(errors.InvalidOnDisableError) as exc:

        class NotStatic(module.Module):
            def on_disable():  # type: ignore[no-redefined-builtin]
                pass

    msg = str(exc.value)
    assert "on_disable must be declared as @staticmethod" in msg


def test_on_disable_must_take_no_parameters():
    with pytest.raises(errors.InvalidOnDisableError) as exc:

        class HasArgs(module.Module):
            @staticmethod
            def on_disable(x):  # type: ignore[unused-argument]
                pass

    msg = str(exc.value)
    assert "on_disable must take no parameters" in msg


SOME_CONST = 42  # noqa: F841


def test_on_disable_must_not_use_module_level_globals():
    with pytest.raises(errors.InvalidOnDisableError) as exc:

        class UsesGlobal(module.Module):
            @staticmethod
            def on_disable():
                # will compile as LOAD_GLOBAL for SOME_CONST
                print(SOME_CONST)

    msg = str(exc.value)
    assert "on_disable uses nonlocal/global names" in msg
    assert "SOME_CONST" in msg


def test_on_disable_must_not_close_over_outer_variables():
    # closure over outer local -> should be rejected via co_freevars on inner code
    with pytest.raises(errors.InvalidOnDisableError) as exc:

        class Closure(module.Module):
            @staticmethod
            def on_disable():
                x = 1

                def inner():
                    # closes over x
                    print(x)  # pragma: no cover

                inner()

    msg = str(exc.value)
    assert "must not close over outer variables" in msg


def test_on_disable_nested_function_without_closure_is_allowed():
    class NestedNoClosure(module.Module):
        def __init__(self):
            super().__init__("nested_no_closure")

        @staticmethod
        def on_disable():
            # nested function that only uses arguments / builtins
            def inner(msg: str) -> None:
                print(msg)

            inner("OK")

    # If the class definition above passed without raising, validation succeeded.
    m = NestedNoClosure()
    assert m.name == "nested_no_closure"


def test_on_disable_can_use_builtins_and_imports_inside_function():
    class Valid(module.Module):
        def __init__(self):
            super().__init__("valid")

        @staticmethod
        def on_disable():
            import math

            print("sqrt2", round(math.sqrt(2), 3))

    v = Valid()
    assert v.name == "valid"


def test_write_on_disable_script_returns_none_when_no_on_disable(tmp_path):
    class NoOnDisable(module.Module):
        def __init__(self):
            super().__init__("no_on_disable")

    m = NoOnDisable()
    script_path = module.write_on_disable_script(m, str(tmp_path))
    assert script_path is None
    assert not list(tmp_path.iterdir())


def test_write_on_disable_script_creates_executable_script(tmp_path):
    class Simple(module.Module):
        def __init__(self):
            super().__init__("Simple")

        @staticmethod
        def on_disable():
            print("ON_DISABLE_RUN")

    m = Simple()
    out_dir = tmp_path / "scripts"
    out_dir.mkdir()

    script_path_str = module.write_on_disable_script(m, str(out_dir))
    assert script_path_str is not None

    script_path = Path(script_path_str)
    assert script_path.exists()

    mode = script_path.stat().st_mode
    assert mode & stat.S_IXUSR, "script must be executable by owner"

    content = script_path.read_text(encoding="utf-8")
    assert "generated from" in content
    assert "def on_disable" in content
    assert 'if __name__ == "__main__":' in content

    # Execute the generated script and check its output
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert "ON_DISABLE_RUN" in proc.stdout


def test_write_on_disable_script_uses_module_and_class_in_header(tmp_path):
    class HeaderCheck(module.Module):
        def __init__(self):
            super().__init__("HeaderCheck")

        @staticmethod
        def on_disable():
            print("HEADER_CHECK")

    m = HeaderCheck()
    script_path_str = module.write_on_disable_script(m, str(tmp_path))
    assert script_path_str is not None

    script_path = Path(script_path_str)
    content = script_path.read_text(encoding="utf-8")

    # header should reference original module and class
    assert f"{HeaderCheck.__module__}.{HeaderCheck.__name__}.on_disable" in content
