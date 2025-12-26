import typing

import pytest

import decman


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
