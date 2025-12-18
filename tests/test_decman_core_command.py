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
