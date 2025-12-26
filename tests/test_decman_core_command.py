import json
import sys
import typing

import pytest

import decman.core.command as command
import decman.core.output


def test_prg_pty_true_uses_pty_run_and_check(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, typing.Any] = {}

    def fake_pty_run(cmd, user=None, env_overrides=None, pass_environment=None, mimic_login=False):
        calls["pty_run"] = (cmd, user, env_overrides, mimic_login)
        return 0, "ok"

    def fake_check_run_result(cmd, result, include_output=None):
        calls["check_run_result"] = (cmd, result)
        return result

    def fake_print_warning(msg: str):
        raise AssertionError("print_warning must not be called when code == 0")

    monkeypatch.setattr(command, "pty_run", fake_pty_run)
    monkeypatch.setattr(command, "check_run_result", fake_check_run_result)
    monkeypatch.setattr(decman.core.output, "print_warning", fake_print_warning)

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

    def fake_run(cmd, user=None, env_overrides=None, pass_environment=None, mimic_login=False):
        calls["run"] = (cmd, user, env_overrides, mimic_login)
        return 0, "no-pty"

    def fake_check_run_result(cmd, result, include_output=None):
        return result

    def fake_print_warning(msg: str):
        raise AssertionError("print_warning must not be called when code == 0")

    monkeypatch.setattr(command, "run", fake_run)
    monkeypatch.setattr(command, "check_run_result", fake_check_run_result)
    monkeypatch.setattr(decman.core.output, "print_warning", fake_print_warning)

    out = decman.prg(["true"], pty=False, check=True)

    assert out == "no-pty"
    assert calls["run"] == (["true"], None, None, False)


def test_prg_check_false_warns_on_nonzero(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, typing.Any] = {}

    def fake_run(cmd, user=None, env_overrides=None, pass_environment=None, mimic_login=False):
        # non-zero exit code
        return 3, "bad"

    def fake_check_run_result(cmd, result, include_output=None):
        raise AssertionError("check_run_result must not be called when check=False")

    def fake_print_warning(msg: str):
        calls["warning"] = msg

    monkeypatch.setattr(command, "run", fake_run)
    monkeypatch.setattr(command, "check_run_result", fake_check_run_result)
    monkeypatch.setattr(decman.core.output, "print_warning", fake_print_warning)

    out = decman.prg(["cmd", "arg"], pty=False, check=False)

    assert out == "bad"
    assert "cmd arg" in calls["warning"]
    assert "exit code 3" in calls["warning"]


def test_prg_check_true_propagates_command_failed_error(monkeypatch: pytest.MonkeyPatch):
    class CommandFailedError(Exception):
        pass

    def fake_run(cmd, user=None, env_overrides=None, pass_environment=None, mimic_login=False):
        return 42, "boom"

    def fake_check_run_result(cmd, result, include_output=None):
        raise CommandFailedError((cmd, result))

    def fake_print_warning(msg: str):
        raise AssertionError("print_warning must not be called when check=True and error")

    monkeypatch.setattr(command, "run", fake_run)
    monkeypatch.setattr(command, "check_run_result", fake_check_run_result)
    monkeypatch.setattr(decman.core.output, "print_warning", fake_print_warning)

    with pytest.raises(CommandFailedError):
        decman.prg(["boom"], pty=False, check=True)


def test_run_simple():
    code, out = command.run([sys.executable, "-c", "print('ok')"])
    assert code == 0
    assert out.strip() == "ok"


def test_run_exec_failure():
    code, out = command.run(["/does/not/exist"])
    assert code != 0
    assert "not" in out.lower()


def test_run_env_overrides_visible_in_child(monkeypatch):
    code, out = command.run(
        [
            sys.executable,
            "-c",
            ("import os, json; print(json.dumps({'FOO': os.environ['FOO'], }))"),
        ],
        env_overrides={"FOO": "BAR"},
    )

    assert code == 0

    data = json.loads(out.strip())
    assert data["FOO"] == "BAR"


@pytest.mark.skipif(not sys.stdin.isatty(), reason="requires TTY")
def test_pty_run_simple():
    code, out = command.pty_run([sys.executable, "-c", "print('ok')"])
    assert code == 0
    assert "ok" in out
    assert "\r\n" not in out
