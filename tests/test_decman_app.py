import argparse
import types

import pytest

import decman.app as app  # adjust if run_decman lives elsewhere


class DummyStore:
    def __init__(self, enabled=None, scripts=None):
        self._data = {}
        if enabled is not None:
            self._data["enabled_modules"] = list(enabled)
        if scripts is not None:
            self._data["module_on_disable_scripts"] = dict(scripts)

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def ensure(self, key, default):
        self._data.setdefault(key, default)


class DummyModule:
    def __init__(self, name):
        self.name = name
        self._changed = False
        self.before_update_called = False
        self.on_enable_called = False
        self.on_change_called = False
        self.after_update_called = False

    def before_update(self, store):
        self.before_update_called = True

    def on_enable(self, store):
        self.on_enable_called = True

    def on_change(self, store):
        self.on_change_called = True

    def after_update(self, store):
        self.after_update_called = True

    @staticmethod
    def on_disable():
        print("Disabled")


class DummyPlugin:
    def __init__(self, apply_result=True):
        self.process_modules_called = False
        self.apply_called_with = None
        self.apply_result = apply_result

    def process_modules(self, store, modules):
        self.process_modules_called = True

    def apply(self, store, dry_run=False, params=None):
        self.apply_called_with = dry_run
        return self.apply_result


def make_args(
    only=None,
    skip=None,
    dry_run=False,
    no_hooks=False,
):
    return argparse.Namespace(
        only=only, skip=skip or [], dry_run=dry_run, no_hooks=no_hooks, params=[]
    )


@pytest.fixture
def no_op_output(monkeypatch):
    ns = types.SimpleNamespace(
        print_debug=lambda *a, **k: None,
        print_summary=lambda *a, **k: None,
        print_info=lambda *a, **k: None,
        print_warning=lambda *a, **k: None,
    )
    monkeypatch.setattr(app, "output", ns)
    return ns


@pytest.fixture
def base_decman(monkeypatch):
    # Ensure decman attribute exists on app and has the fields we need
    dm = types.SimpleNamespace()
    dm.execution_order = []
    dm.modules = []
    dm.files = []
    dm.directories = []
    dm.symlinks = {}
    dm.plugins = {}
    dm.prg_calls = []

    def prg(cmd):
        dm.prg_calls.append(cmd)

    dm.prg = prg

    monkeypatch.setattr(app, "decman", dm)
    return dm


@pytest.fixture
def file_manager(monkeypatch):
    fm = types.SimpleNamespace()
    fm.update_files_calls = []
    fm.result = True

    def update_files(store, modules, files, directories, symlinks, dry_run=False):
        fm.update_files_calls.append(
            dict(
                store=store,
                modules=list(modules),
                files=list(files),
                directories=list(directories),
                symlinks=list(symlinks),
                dry_run=dry_run,
            )
        )
        return fm.result

    fm.update_files = update_files
    monkeypatch.setattr(app, "file_manager", fm)
    return fm


def test_execution_order_only_and_skip(no_op_output, base_decman, file_manager):
    base_decman.execution_order = ["files", "plugin_a", "plugin_b"]

    args = make_args(
        only=["files", "plugin_b"],
        skip=["plugin_b"],
        dry_run=True,
        no_hooks=True,
    )
    store = DummyStore()

    plugin = DummyPlugin(apply_result=False)
    base_decman.plugins = {"plugin_b": plugin}

    result = app.run_decman(store, args)

    assert result is True
    # Should have run only "files"
    assert len(file_manager.update_files_calls) == 1
    assert file_manager.update_files_calls[0]["dry_run"] is True


def test_returns_false_when_update_files_fails_and_skips_plugins(
    no_op_output, base_decman, file_manager
):
    base_decman.execution_order = ["files", "plugin_a"]

    plugin = DummyPlugin(apply_result=True)
    base_decman.plugins = {"plugin_a": plugin}

    file_manager.result = False  # update_files fails

    args = make_args(dry_run=False, no_hooks=True)
    store = DummyStore()

    result = app.run_decman(store, args)

    assert result is False
    # update_files called once
    assert len(file_manager.update_files_calls) == 1
    # plugin should never be touched
    assert plugin.process_modules_called is False
    assert plugin.apply_called_with is None


def test_plugin_failure_returns_false(no_op_output, base_decman, file_manager):
    base_decman.execution_order = ["plugin_a"]
    plugin = DummyPlugin(apply_result=False)
    base_decman.plugins = {"plugin_a": plugin}

    args = make_args(dry_run=False, no_hooks=True)
    store = DummyStore()

    result = app.run_decman(store, args)

    assert result is False
    assert plugin.process_modules_called is True
    assert plugin.apply_called_with is False
    # No file updates
    assert file_manager.update_files_calls == []


def test_disabled_modules_run_on_disable_script(no_op_output, base_decman, file_manager):
    # enabled_modules contains a module that no longer exists
    store = DummyStore(
        enabled=["present", "old_mod"],
        scripts={"old_mod": "/tmp/on_disable.sh"},
    )

    # Only "present" exists now, so "old_mod" is disabled
    base_decman.modules = [DummyModule("present")]
    base_decman.execution_order = []

    args = make_args(dry_run=False, no_hooks=False)

    result = app.run_decman(store, args)

    assert result is True
    # prg should be called with the script for old_mod
    assert base_decman.prg_calls == [["/tmp/on_disable.sh"]]
    assert store["enabled_modules"] == ["present"]
    assert store["module_on_disable_scripts"] == {}


def test_on_disable_not_run_in_dry_run(no_op_output, base_decman, file_manager):
    store = DummyStore(
        enabled=["present", "old_mod"],
        scripts={"old_mod": "/tmp/on_disable.sh"},
    )
    base_decman.modules = [DummyModule("present")]
    base_decman.execution_order = []

    args = make_args(dry_run=True, no_hooks=True)

    result = app.run_decman(store, args)

    assert result is True
    # dry_run: on_disable scripts must not be executed
    assert base_decman.prg_calls == []


def test_hooks_called_for_new_and_changed_modules(
    no_op_output, base_decman, file_manager, monkeypatch, tmp_path
):
    m1 = DummyModule("mod1")
    m2 = DummyModule("mod2")
    m1._changed = True
    m2._changed = False

    base_decman.modules = [m1, m2]
    base_decman.execution_order = []  # no steps, just hooks

    monkeypatch.setattr("decman.config.module_on_disable_scripts_dir", tmp_path)

    # Only mod2 was previously enabled, so mod1 is "new"
    store = DummyStore(enabled=["mod2"])

    args = make_args(dry_run=False, no_hooks=False)

    result = app.run_decman(store, args)

    assert result is True

    # before_update for all modules
    assert m1.before_update_called is True
    assert m2.before_update_called is True

    # on_enable only for new module (mod1)
    assert m1.on_enable_called is True
    assert m2.on_enable_called is False

    # on_change only for modules with _changed
    assert m1.on_change_called is True
    assert m2.on_change_called is False

    # after_update for all modules
    assert m1.after_update_called is True
    assert m2.after_update_called is True

    assert store["enabled_modules"] == ["mod2", "mod1"]
    assert store["module_on_disable_scripts"] == {"mod1": str(tmp_path / "mod1_on_disable.py")}


def test_hooks_not_called_when_no_hooks(no_op_output, base_decman, file_manager):
    m1 = DummyModule("mod1")
    m1._changed = True

    base_decman.modules = [m1]
    base_decman.execution_order = []

    store = DummyStore(enabled=["mod1"])

    args = make_args(dry_run=False, no_hooks=True)

    result = app.run_decman(store, args)

    assert result is True

    assert m1.before_update_called is False
    assert m1.on_enable_called is False
    assert m1.on_change_called is False
    assert m1.after_update_called is False


def test_dry_run_skips_all_hooks_but_runs_steps_with_flag(no_op_output, base_decman, file_manager):
    m1 = DummyModule("mod1")
    m1._changed = True
    base_decman.modules = [m1]

    base_decman.execution_order = ["files", "plugin_a"]
    plugin = DummyPlugin(apply_result=True)
    base_decman.plugins = {"plugin_a": plugin}

    store = DummyStore()
    args = make_args(dry_run=True, no_hooks=False)

    result = app.run_decman(store, args)

    assert result is True

    # Steps executed with dry_run=True
    assert len(file_manager.update_files_calls) == 1
    assert file_manager.update_files_calls[0]["dry_run"] is True
    assert plugin.process_modules_called is True
    assert plugin.apply_called_with is True

    # All hooks skipped due to dry_run
    assert m1.before_update_called is False
    assert m1.on_enable_called is False
    assert m1.on_change_called is False
    assert m1.after_update_called is False


def test_missing_plugin_emits_warning_but_continues(base_decman, file_manager, monkeypatch):
    warnings = []

    def warn(msg):
        warnings.append(msg)

    out = types.SimpleNamespace(
        print_debug=lambda *a, **k: None,
        print_summary=lambda *a, **k: None,
        print_info=lambda *a, **k: None,
        print_warning=warn,
    )
    monkeypatch.setattr(app, "output", out)

    base_decman.execution_order = ["unknown_plugin"]
    base_decman.plugins = {}  # none available

    store = DummyStore()
    args = make_args(dry_run=True, no_hooks=True)

    result = app.run_decman(store, args)

    assert result is True
    assert any("unknown_plugin" in w for w in warnings)
