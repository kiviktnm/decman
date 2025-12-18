import builtins
import types

import pytest

import decman.config as config
import decman.core.output as output


@pytest.fixture(autouse=True)
def reset_config():
    # snapshot & restore config flags between tests
    orig = types.SimpleNamespace(
        debug_output=getattr(config, "debug_output", False),
        quiet_output=getattr(config, "quiet_output", False),
        color_output=getattr(config, "color_output", True),
    )
    yield
    config.debug_output = orig.debug_output
    config.quiet_output = orig.quiet_output
    config.color_output = orig.color_output


def test_print_error_with_color_enabled(capsys):
    config.color_output = True
    output.print_error("boom")

    out = capsys.readouterr().out
    assert "boom" in out
    assert "ERROR" in out
    # crude check that some ANSI escapes are present
    assert "\x1b[" in out


def test_print_error_with_color_disabled(capsys):
    config.color_output = False
    output.print_error("boom")

    out = capsys.readouterr().out
    assert out.strip().endswith("ERROR: boom")
    # no ANSI escapes
    assert "\x1b[" not in out


def test_print_info_respects_quiet_and_debug(capsys):
    config.quiet_output = True
    config.debug_output = False

    output.print_info("msg 1")
    out = capsys.readouterr().out
    assert out == ""  # suppressed

    config.debug_output = True
    output.print_info("msg 2")
    out = capsys.readouterr().out
    assert "INFO: msg 2" in out

    config.quiet_output = False
    config.debug_output = False
    output.print_info("msg 3")
    out = capsys.readouterr().out
    assert "INFO: msg 3" in out


def test_print_debug_only_with_debug_enabled(capsys):
    config.debug_output = False
    output.print_debug("dbg")
    assert capsys.readouterr().out == ""

    config.debug_output = True
    output.print_debug("dbg")
    out = capsys.readouterr().out
    assert "DEBUG" in out
    assert "dbg" in out


def test_print_continuation_respects_level_and_config(capsys):
    config.quiet_output = True
    config.debug_output = False

    output.print_continuation("x", level=output.INFO)
    assert capsys.readouterr().out == ""

    output.print_continuation("y", level=output.SUMMARY)
    out = capsys.readouterr().out
    assert "y" in out


def test_print_list_empty_outputs_nothing(capsys):
    output.print_list("Header", [])
    assert capsys.readouterr().out == ""


def test_print_list_summary_and_elements(capsys, monkeypatch):
    # fixed terminal size for deterministic wrapping
    monkeypatch.setattr(
        output.shutil, "get_terminal_size", lambda: types.SimpleNamespace(columns=80)
    )
    config.quiet_output = False
    config.debug_output = False

    output.print_list("Installed packages:", ["a", "b", "c"])

    out = capsys.readouterr().out.splitlines()
    # header summary
    assert any("SUMMARY" in line and "Installed packages:" in line for line in out)
    # list content printed as continuation lines
    assert any("a" in line for line in out)
    assert any("b" in line for line in out)
    assert any("c" in line for line in out)


def test_print_list_respects_elements_per_line_and_width(capsys, monkeypatch):
    # very small width to force wrapping
    monkeypatch.setattr(
        output.shutil, "get_terminal_size", lambda: types.SimpleNamespace(columns=30)
    )

    items = [f"pkg{i}" for i in range(5)]
    output.print_list(
        "Pkgs:",
        items,
        elements_per_line=2,
        limit_to_term_size=True,
        level=output.SUMMARY,
    )

    out_lines = capsys.readouterr().out.splitlines()
    list_lines = [l for l in out_lines if "pkg" in l]
    # at most 2 per line
    for line in list_lines:
        assert len([p for p in items if p in line]) <= 2


def test_prompt_number_valid_input(monkeypatch):
    inputs = iter(["3"])
    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    res = output.prompt_number("Pick", 1, 5)
    assert res == 3


def test_prompt_number_invalid_then_valid(monkeypatch, capsys):
    inputs = iter(["foo", "10", "2"])
    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    res = output.prompt_number("Pick", 1, 5)
    assert res == 2

    out = capsys.readouterr().out
    # at least one error printed
    assert "Invalid input" in out


def test_prompt_number_default_on_empty(monkeypatch):
    inputs = iter([""])
    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    res = output.prompt_number("Pick", 1, 5, default=4)
    assert res == 4


@pytest.mark.parametrize(
    "user_input,default,expected",
    [
        ("y", None, True),
        ("Y", None, True),
        ("yes", None, True),
        ("n", None, False),
        ("No", None, False),
        ("", True, True),
        ("", False, False),
    ],
)
def test_prompt_confirm(monkeypatch, user_input, default, expected):
    inputs = iter([user_input])
    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    res = output.prompt_confirm("Continue?", default=default)
    assert res is expected


def test_prompt_confirm_invalid_then_yes(monkeypatch, capsys):
    inputs = iter(["maybe", "y"])
    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    res = output.prompt_confirm("Continue?")
    assert res is True

    out = capsys.readouterr().out
    assert "Invalid input." in out
