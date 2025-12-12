import json
import sys

import pytest

import decman.core.command as command


def test_run_simple():
    code, out = command.run([sys.executable, "-c", "print('ok')"])
    assert code == 0
    assert out.strip() == "ok"


def test_run_exec_failure():
    code, out = command.run(["/does/not/exist"])
    assert code != 0
    assert "not" in out.lower()


def test_run_env_overrides_and_mimic_login_visible_in_child(monkeypatch):
    class FakePw:
        pw_dir = "/fake/home"
        pw_name = "fakeuser"
        pw_uid = 1000
        pw_gid = 1000
        pw_shell = "/bin/fakesh"

    # Mock passwd lookup
    monkeypatch.setattr(
        "decman.core.command.pwd.getpwnam",
        lambda user: FakePw(),
    )

    code, out = command.run(
        [
            sys.executable,
            "-c",
            (
                "import os, json; "
                "print(json.dumps({"
                "'FOO': os.environ['FOO'], "
                "'HOME': os.environ['HOME'], "
                "'USER': os.environ['USER'], "
                "'LOGNAME': os.environ['LOGNAME'], "
                "'SHELL': os.environ['SHELL']"
                "}))"
            ),
        ],
        user="fakeuser",
        mimic_login=True,
        env_overrides={"FOO": "BAR"},
    )

    assert code == 0

    data = json.loads(out.strip())
    assert data["FOO"] == "BAR"
    assert data["HOME"] == "/fake/home"
    assert data["USER"] == "fakeuser"
    assert data["LOGNAME"] == "fakeuser"
    assert data["SHELL"] == "/bin/fakesh"


@pytest.mark.skipif(not sys.stdin.isatty(), reason="requires TTY")
def test_pty_run_simple():
    code, out = command.pty_run([sys.executable, "-c", "print('ok')"])
    assert code == 0
    assert "ok" in out
    assert "\r\n" not in out
