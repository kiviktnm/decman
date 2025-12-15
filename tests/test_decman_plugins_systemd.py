import pytest

from decman.plugins import systemd as systemd_mod


class DummyStore(dict):
    def ensure(self, key, default):
        if key not in self:
            self[key] = default


class DummyModule:
    def __init__(self, name: str):
        self.name = name
        self._changed = False


@pytest.fixture
def store():
    return DummyStore()


@pytest.fixture
def systemd():
    return systemd_mod.Systemd()


def test_units_decorator_sets_attribute():
    @systemd_mod.units
    def fn():
        pass

    assert getattr(fn, "__systemd__units__", False) is True


def test_user_units_decorator_sets_attribute():
    @systemd_mod.user_units
    def fn():
        pass

    assert getattr(fn, "__systemd__user__units__", False) is True


def test_available_true_if_systemctl_found(monkeypatch, systemd):
    called = {}

    def fake_which(name):
        called["name"] = name
        return "/bin/systemctl"

    monkeypatch.setattr(systemd_mod.shutil, "which", fake_which)
    assert systemd.available() is True
    assert called["name"] == "systemctl"


def test_available_false_if_systemctl_missing(monkeypatch, systemd):
    monkeypatch.setattr(systemd_mod.shutil, "which", lambda name: None)
    assert systemd.available() is False


def test_process_modules_marks_changed_and_updates_store(monkeypatch, store, systemd):
    # initial store empty; ensure keys will be created
    m1 = DummyModule("mod1")
    m2 = DummyModule("mod2")

    def fake_run_method(mod, attr):
        if mod is m1 and attr == "__systemd__units__":
            return {"a.service"}
        if mod is m1 and attr == "__systemd__user__units__":
            return {"alice": {"u1.service"}}
        # m2 has no units
        return None

    monkeypatch.setattr(systemd_mod.plugins, "run_method_with_attribute", fake_run_method)

    systemd.process_modules(store, {m1, m2})

    # m1 changed from default -> marked _changed
    assert m1._changed is True
    # m2 had no units
    assert m2._changed is False

    # enabled units aggregated
    assert systemd.enabled_units == {"a.service"}
    assert systemd.enabled_user_units == {"alice": {"u1.service"}}

    # store updated per module
    assert store["systemd_units_for_module"]["mod1"] == {"a.service"}
    assert store["systemd_user_units_for_module"]["mod1"] == {"alice": {"u1.service"}}
    assert store["systemd_units_for_module"]["mod2"] == set()
    assert store["systemd_user_units_for_module"]["mod2"] == {}


def test_process_modules_no_change_second_run(monkeypatch, store, systemd):
    m1 = DummyModule("mod1")

    def fake_run_method(mod, attr):
        if attr == "__systemd__units__":
            return {"a.service"}
        if attr == "__systemd__user__units__":
            return {"alice": {"u1.service"}}
        return None

    monkeypatch.setattr(systemd_mod.plugins, "run_method_with_attribute", fake_run_method)

    # first run populates store
    systemd.process_modules(store, {m1})
    m1._changed = False

    # new instance (fresh per-process in real usage)
    systemd2 = systemd_mod.Systemd()
    monkeypatch.setattr(systemd_mod.plugins, "run_method_with_attribute", fake_run_method)

    systemd2.process_modules(store, {m1})

    # values in store are same -> _changed stays False
    assert m1._changed is False


def test_apply_enables_and_disables_units_and_user_units(store):
    s = systemd_mod.Systemd()

    # Current enabled according to modules
    s.enabled_units = {"new.service"}
    s.enabled_user_units = {"alice": {"newuser.service"}}

    # Store says we had an old unit enabled before
    store["systemd_units"] = {"old.service"}
    store["systemd_user_units"] = {"alice": {"olduser.service"}}

    calls = []

    def fake_reload_daemon():
        calls.append(("reload_daemon",))
        return True

    def fake_reload_user_daemon(user):
        calls.append(("reload_user_daemon", user))
        return True

    def fake_enable_units(store_arg, units_arg):
        calls.append(("enable_units", frozenset(units_arg)))
        store_arg["systemd_units"] |= units_arg
        return True

    def fake_disable_units(store_arg, units_arg):
        calls.append(("disable_units", frozenset(units_arg)))
        store_arg["systemd_units"] -= units_arg
        return True

    def fake_enable_user_units(store_arg, units_arg, user):
        calls.append(("enable_user_units", user, frozenset(units_arg)))
        store_arg["systemd_user_units"].setdefault(user, set()).update(units_arg)
        return True

    def fake_disable_user_units(store_arg, units_arg, user):
        calls.append(("disable_user_units", user, frozenset(units_arg)))
        store_arg["systemd_user_units"].setdefault(user, set()).difference_update(units_arg)
        return True

    # patch instance methods (no self parameter expected)
    s.reload_daemon = fake_reload_daemon
    s.reload_user_daemon = fake_reload_user_daemon
    s.enable_units = fake_enable_units
    s.disable_units = fake_disable_units
    s.enable_user_units = fake_enable_user_units
    s.disable_user_units = fake_disable_user_units

    result = s.apply(store, dry_run=False, params=None)
    assert result is True

    # reloads called once
    assert ("reload_daemon",) in calls
    assert ("reload_user_daemon", "alice") in calls

    # enable/disable correct units
    assert ("enable_units", frozenset({"new.service"})) in calls
    assert ("disable_units", frozenset({"old.service"})) in calls
    assert ("enable_user_units", "alice", frozenset({"newuser.service"})) in calls
    assert ("disable_user_units", "alice", frozenset({"olduser.service"})) in calls

    # store reconciled
    assert store["systemd_units"] == {"new.service"}
    assert store["systemd_user_units"]["alice"] == {"newuser.service"}


def test_apply_dry_run_does_not_mutate_store_or_call_commands(store):
    s = systemd_mod.Systemd()
    s.enabled_units = {"new.service"}
    s.enabled_user_units = {"alice": {"newuser.service"}}

    store["systemd_units"] = {"old.service"}
    store["systemd_user_units"] = {"alice": {"olduser.service"}}

    called = {"reload": False, "enable": False, "disable": False}

    s.reload_daemon = lambda: called.__setitem__("reload", True) or True
    s.reload_user_daemon = lambda user: called.__setitem__("reload", True) or True
    s.enable_units = lambda st, u: called.__setitem__("enable", True) or True
    s.disable_units = lambda st, u: called.__setitem__("disable", True) or True
    s.enable_user_units = lambda st, u, user: called.__setitem__("enable", True) or True
    s.disable_user_units = lambda st, u, user: called.__setitem__("disable", True) or True

    result = s.apply(store, dry_run=True, params=None)
    assert result is True

    # no commands should be called
    assert called == {"reload": False, "enable": False, "disable": False}

    # store unchanged
    assert store["systemd_units"] == {"old.service"}
    assert store["systemd_user_units"]["alice"] == {"olduser.service"}


def test_enable_units_success(monkeypatch, store, systemd):
    store["systemd_units"] = {"old.service"}

    def fake_run(cmd):
        assert cmd[0] == "systemctl"
        assert cmd[1] == "enable"
        assert "new.service" in cmd[2:]
        return 0, "ok"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)

    result = systemd.enable_units(store, {"new.service"})
    assert result is True
    assert store["systemd_units"] == {"old.service", "new.service"}


def test_enable_units_failure_does_not_update_store(monkeypatch, store, systemd):
    store["systemd_units"] = {"old.service"}

    def fake_run(cmd):
        return 1, "error"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)

    result = systemd.enable_units(store, {"new.service"})
    assert result is False
    # unchanged
    assert store["systemd_units"] == {"old.service"}


def test_disable_units_success(monkeypatch, store, systemd):
    store["systemd_units"] = {"old.service", "new.service"}

    def fake_run(cmd):
        assert cmd[0] == "systemctl"
        assert cmd[1] == "disable"
        assert "new.service" in cmd[2:]
        return 0, "ok"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)

    result = systemd.disable_units(store, {"new.service"})
    assert result is True
    assert store["systemd_units"] == {"old.service"}


def test_disable_units_failure_does_not_update_store(monkeypatch, store, systemd):
    store["systemd_units"] = {"old.service", "new.service"}

    def fake_run(cmd):
        return 1, "error"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)

    result = systemd.disable_units(store, {"new.service"})
    assert result is False
    assert store["systemd_units"] == {"old.service", "new.service"}


def test_enable_user_units_success(monkeypatch, store, systemd):
    store["systemd_user_units"] = {"alice": {"olduser.service"}}

    def fake_run(cmd):
        assert cmd[0] == "systemctl"
        assert "--user" in cmd
        assert "enable" in cmd
        assert "newuser.service" in cmd
        return 0, "ok"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)

    result = systemd.enable_user_units(store, {"newuser.service"}, "alice")
    assert result is True
    assert store["systemd_user_units"]["alice"] == {
        "olduser.service",
        "newuser.service",
    }


def test_enable_user_units_failure_does_not_update_store(monkeypatch, store, systemd):
    store["systemd_user_units"] = {"alice": {"olduser.service"}}

    def fake_run(cmd):
        return 1, "error"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)

    result = systemd.enable_user_units(store, {"newuser.service"}, "alice")
    assert result is False
    assert store["systemd_user_units"]["alice"] == {"olduser.service"}


def test_disable_user_units_success(monkeypatch, store, systemd):
    store["systemd_user_units"] = {"alice": {"olduser.service", "newuser.service"}}

    def fake_run(cmd):
        assert cmd[0] == "systemctl"
        assert "--user" in cmd
        assert "disable" in cmd
        assert "newuser.service" in cmd
        return 0, "ok"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)

    result = systemd.disable_user_units(store, {"newuser.service"}, "alice")
    assert result is True
    assert store["systemd_user_units"]["alice"] == {"olduser.service"}


def test_disable_user_units_failure_does_not_update_store(monkeypatch, store, systemd):
    store["systemd_user_units"] = {"alice": {"olduser.service", "newuser.service"}}

    def fake_run(cmd):
        return 1, "error"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)

    result = systemd.disable_user_units(store, {"newuser.service"}, "alice")
    assert result is False
    assert store["systemd_user_units"]["alice"] == {
        "olduser.service",
        "newuser.service",
    }


def test_reload_daemon_uses_command_run(monkeypatch, systemd):
    called = {}

    def fake_run(cmd):
        called["cmd"] = cmd
        return 0, "ok"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)
    result = systemd.reload_daemon()
    assert result is True
    assert called["cmd"][:2] == ["systemctl", "daemon-reload"]


def test_reload_user_daemon_uses_command_run(monkeypatch, systemd):
    called = {}

    def fake_run(cmd):
        called["cmd"] = cmd
        return 0, "ok"

    monkeypatch.setattr(systemd_mod.command, "run", fake_run)
    result = systemd.reload_user_daemon("alice")
    assert result is True
    cmd = called["cmd"]
    assert cmd[0] == "systemctl"
    assert "--user" in cmd
    assert "daemon-reload" in cmd
