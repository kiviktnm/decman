import typing

import pytest

import decman


def test_prg_pty_true_uses_pty_run_and_check(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, typing.Any] = {}

    def fake_pty_run(cmd, user=None, env_overrides=None, mimic_login=False):
        calls["pty_run"] = (cmd, user, env_overrides, mimic_login)
        return 0, "ok"

    def fake_check_run_result(cmd, result):
        calls["check_run_result"] = (cmd, result)
        return result

    def fake_print_warning(msg: str):
        raise AssertionError("print_warning must not be called when code == 0")

    monkeypatch.setattr(decman, "command", decman.command)
    monkeypatch.setattr(decman.command, "pty_run", fake_pty_run)
    monkeypatch.setattr(decman.command, "check_run_result", fake_check_run_result)
    monkeypatch.setattr(decman, "output", decman.output)
    monkeypatch.setattr(decman.output, "print_warning", fake_print_warning)

    out = decman.prg(
        ["echo", "hi"],
        user="alice",
        env_overrides={"FOO": "bar"},
        mimic_login=True,
        pty=True,
        check=True,
    )

    assert out == "ok"
    assert calls["pty_run"] == (["echo", "hi"], "alice", {"FOO": "bar"}, True)
    assert calls["check_run_result"] == (["echo", "hi"], (0, "ok"))


def test_prg_pty_false_uses_run(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, typing.Any] = {}

    def fake_run(cmd, user=None, env_overrides=None, mimic_login=False):
        calls["run"] = (cmd, user, env_overrides, mimic_login)
        return 0, "no-pty"

    def fake_check_run_result(cmd, result):
        return result

    def fake_print_warning(msg: str):
        raise AssertionError("print_warning must not be called when code == 0")

    monkeypatch.setattr(decman.command, "run", fake_run)
    monkeypatch.setattr(decman.command, "check_run_result", fake_check_run_result)
    monkeypatch.setattr(decman.output, "print_warning", fake_print_warning)

    out = decman.prg(["true"], pty=False, check=True)

    assert out == "no-pty"
    assert calls["run"] == (["true"], None, None, False)


def test_prg_check_false_warns_on_nonzero(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, typing.Any] = {}

    def fake_run(cmd, user=None, env_overrides=None, mimic_login=False):
        # non-zero exit code
        return 3, "bad"

    def fake_check_run_result(cmd, result):
        raise AssertionError("check_run_result must not be called when check=False")

    def fake_print_warning(msg: str):
        calls["warning"] = msg

    monkeypatch.setattr(decman.command, "run", fake_run)
    monkeypatch.setattr(decman.command, "check_run_result", fake_check_run_result)
    monkeypatch.setattr(decman.output, "print_warning", fake_print_warning)

    out = decman.prg(["cmd", "arg"], pty=False, check=False)

    assert out == "bad"
    assert "cmd arg" in calls["warning"]
    assert "exit code 3" in calls["warning"]


def test_prg_check_true_propagates_command_failed_error(monkeypatch: pytest.MonkeyPatch):
    class CommandFailedError(Exception):
        pass

    def fake_run(cmd, user=None, env_overrides=None, mimic_login=False):
        return 42, "boom"

    def fake_check_run_result(cmd, result):
        raise CommandFailedError((cmd, result))

    def fake_print_warning(msg: str):
        raise AssertionError("print_warning must not be called when check=True and error")

    monkeypatch.setattr(decman.command, "run", fake_run)
    monkeypatch.setattr(decman.command, "check_run_result", fake_check_run_result)
    monkeypatch.setattr(decman.output, "print_warning", fake_print_warning)

    with pytest.raises(CommandFailedError):
        decman.prg(["boom"], pty=False, check=True)


def test_sh_calls_prg_with_sh_command(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, typing.Any] = {}

    def fake_prg(
        cmd,
        user=None,
        env_overrides=None,
        mimic_login=False,
        pty=True,
        check=True,
    ):
        calls["prg"] = (cmd, user, env_overrides, mimic_login, pty, check)
        return "output-from-prg"

    monkeypatch.setattr(decman, "prg", fake_prg)

    out = decman.sh(
        "echo test",
        user="bob",
        env_overrides={"X": "1"},
        mimic_login=True,
        pty=False,
        check=False,
    )

    assert out == "output-from-prg"

    cmd, user, env_overrides, mimic_login, pty, check = calls["prg"]
    assert cmd == ["/bin/sh", "-c", "echo test"]
    assert user == "bob"
    assert env_overrides == {"X": "1"}
    assert mimic_login is True
    assert pty is False
    assert check is False
