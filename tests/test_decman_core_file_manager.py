import os

import pytest

import decman.core.error as errors
import decman.core.output as output
from decman.core.file_manager import (
    _install_directories,
    _install_files,
    _install_symlinks,
    update_files,
)


class DummyFile:
    def __init__(self, result=True, exc: BaseException | None = None):
        self.result = result
        self.exc = exc
        self.source_file = None
        self.calls: list[tuple[str, dict | None, bool]] = []

    def copy_to(self, target: str, variables=None, dry_run: bool = False) -> bool:
        self.calls.append((target, variables, dry_run))
        if self.exc is not None:
            raise self.exc
        return self.result


class DummyDirectory:
    def __init__(
        self,
        checked: list[str] | None = None,
        changed: list[str] | None = None,
        exc: BaseException | None = None,
        source_directory: str = "<src>",
    ):
        self.checked = checked or []
        self.changed = changed or []
        self.exc = exc
        self.source_directory = source_directory
        self.calls: list[tuple[str, dict | None, bool]] = []

    def copy_to(self, target: str, variables=None, dry_run: bool = False):
        self.calls.append((target, variables, dry_run))
        if self.exc is not None:
            raise self.exc
        return self.checked, self.changed


class DummyModule:
    def __init__(
        self,
        name: str,
        file_map: dict[str, DummyFile] | None = None,
        dir_map: dict[str, DummyDirectory] | None = None,
        symlink_map: dict[str, str] | None = None,
        file_vars: dict[str, str] | None = None,
    ):
        self.name = name
        self._file_map = file_map or {}
        self._dir_map = dir_map or {}
        self._file_vars = file_vars or {}
        self._symlink_map = symlink_map or {}
        self._changed = False

    def files(self):
        return self._file_map

    def directories(self):
        return self._dir_map

    def symlinks(self):
        return self._symlink_map

    def file_variables(self):
        return self._file_vars


class DummyStore:
    def __init__(self, initial: dict | None = None):
        self._data = dict(initial or {})

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def ensure(self, key, default):
        self._data.setdefault(key, default)


# ---- _install_files -------------------------------------------------------


def test_install_files_non_dry_run_tracks_checked_and_changed():
    f1 = DummyFile(result=True)
    f2 = DummyFile(result=False)
    files = {
        "/tmp/file1": f1,
        "/tmp/file2": f2,
    }

    checked, changed = _install_files(files, variables={"X": "1"}, dry_run=False)

    assert checked == ["/tmp/file1", "/tmp/file2"]
    assert changed == ["/tmp/file1"]

    assert f1.calls == [("/tmp/file1", {"X": "1"}, False)]
    assert f2.calls == [("/tmp/file2", {"X": "1"}, False)]


def test_install_files_dry_run_uses_dry_run_flag_and_respects_return_value():
    f1 = DummyFile(result=True)
    f2 = DummyFile(result=False)
    files = {
        "/tmp/file1": f1,
        "/tmp/file2": f2,
    }

    checked, changed = _install_files(files, variables=None, dry_run=True)

    assert checked == ["/tmp/file1", "/tmp/file2"]
    assert changed == ["/tmp/file1"]  # only ones that "would" change

    assert f1.calls == [("/tmp/file1", None, True)]
    assert f2.calls == [("/tmp/file2", None, True)]


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("nope"),
        OSError("boom"),
        UnicodeEncodeError("utf-8", "x", 0, 1, "bad"),
        UnicodeDecodeError("utf-8", b"x", 0, 1, "bad"),
    ],
)
def test_install_files_wraps_exceptions(exc):
    f = DummyFile(exc=exc)
    files = {"/tmp/file": f}

    with pytest.raises(errors.FSInstallationFailedError) as e:
        _install_files(files, dry_run=False)

    msg = str(e.value)
    assert "/tmp/file" in msg
    assert "content" in msg or "Source file doesn't exist." in msg


# ---- _install_directories -------------------------------------------------


def test_install_directories_aggregates_checked_and_changed():
    d1 = DummyDirectory(
        checked=["/tmp/d1/a", "/tmp/d1/b"],
        changed=["/tmp/d1/a"],
        source_directory="/src/d1",
    )
    d2 = DummyDirectory(
        checked=["/tmp/d2/a"],
        changed=["/tmp/d2/a"],
        source_directory="/src/d2",
    )
    dirs = {
        "/tmp/d1": d1,
        "/tmp/d2": d2,
    }

    checked, changed = _install_directories(dirs, variables={"Y": "2"}, dry_run=False)

    assert checked == ["/tmp/d1/a", "/tmp/d1/b", "/tmp/d2/a"]
    assert changed == ["/tmp/d1/a", "/tmp/d2/a"]

    # dry_run flag and variables propagated
    assert d1.calls == [("/tmp/d1", {"Y": "2"}, False)]
    assert d2.calls == [("/tmp/d2", {"Y": "2"}, False)]


@pytest.mark.parametrize(
    "exc",
    [
        FileNotFoundError("nope"),
        OSError("boom"),
        UnicodeEncodeError("utf-8", "x", 0, 1, "bad"),
        UnicodeDecodeError("utf-8", b"x", 0, 1, "bad"),
    ],
)
def test_install_directories_wraps_exceptions(exc):
    d = DummyDirectory(exc=exc, source_directory="/src")
    dirs = {"/tmp/d": d}

    with pytest.raises(errors.FSInstallationFailedError) as e:
        _install_directories(dirs, dry_run=False)

    msg = str(e.value)
    assert "/tmp/d" in msg
    assert "/src" in msg


# ---- update_files ---------------------------------------------------------


def test_update_files_success_updates_store_and_removes_stale_files(monkeypatch):
    # Prepare common files/dirs
    common_file = DummyFile(result=True)
    common_dir = DummyDirectory(
        checked=["/etc/app/config.d/a.conf"],
        changed=["/etc/app/config.d/a.conf"],
        source_directory="/src/config.d",
    )

    # Module with its own file
    mod_file = DummyFile(result=True)
    m = DummyModule(
        name="mod1",
        file_map={"/etc/app/mod1.conf": mod_file},
        dir_map={},
        file_vars={"FOO": "bar"},
    )

    # Store already has some files, including one stale file
    store = DummyStore(
        {"all_files": ["/etc/app/common.conf", "/etc/app/mod1.conf", "/etc/app/stale.conf"]}
    )

    removed = []

    def fake_remove(path):
        removed.append(path)

    monkeypatch.setattr(os, "remove", fake_remove)

    # Run
    ok = update_files(
        store=store,
        modules={m},
        files={"/etc/app/common.conf": common_file},
        directories={"/etc/app/config.d": common_dir},
        symlinks={},
        dry_run=False,
    )

    assert ok is True

    # common + dir content + module file were re-checked
    assert set(store["all_files"]) == {
        "/etc/app/common.conf",
        "/etc/app/config.d/a.conf",
        "/etc/app/mod1.conf",
    }

    # stale file should be removed
    assert removed == ["/etc/app/stale.conf"]

    # module marked changed because its file changed
    assert m._changed is True

    # copy_to called for all files with correct dry_run flag
    assert common_file.calls == [("/etc/app/common.conf", None, False)]
    assert mod_file.calls == [("/etc/app/mod1.conf", {"FOO": "bar"}, False)]


def test_update_files_dry_run_does_not_touch_store_or_remove(monkeypatch):
    common_file = DummyFile(result=True)
    common_dir = DummyDirectory(
        checked=["/etc/app/config.d/a.conf"],
        changed=["/etc/app/config.d/a.conf"],
        source_directory="/src/config.d",
    )
    m = DummyModule(
        name="mod1",
        file_map={"/etc/app/mod1.conf": DummyFile(result=True)},
        dir_map={},
    )

    store = DummyStore({"all_files": ["/etc/app/common.conf", "/etc/app/stale.conf"]})
    removed = []

    def fake_remove(path):
        removed.append(path)

    monkeypatch.setattr(os, "remove", fake_remove)

    ok = update_files(
        store=store,
        modules={m},
        files={"/etc/app/common.conf": common_file},
        directories={"/etc/app/config.d": common_dir},
        symlinks={},
        dry_run=True,
    )

    assert ok is True

    # Store unchanged
    assert store["all_files"] == ["/etc/app/common.conf", "/etc/app/stale.conf"]

    # No removals
    assert removed == []

    # copy_to called with dry_run=True
    assert common_file.calls == [("/etc/app/common.conf", None, True)]


def test_update_files_propagates_fsinstallation_error_and_does_not_modify_store(monkeypatch):
    # Use real store.Store to ensure interface compatibility if you prefer
    store = DummyStore({"all_files": ["/etc/app/keep.conf"]})

    # Fake failing _install_files
    def failing_install_files(*args, **kwargs):
        raise errors.FSInstallationFailedError("content", "/etc/app/broken.conf", "fail")

    # Capture deletes
    removed = []

    def fake_remove(path):
        removed.append(path)

    # Spy on output error/traceback so they exist but don't blow up
    error_msgs = []

    def fake_print_error(msg):
        error_msgs.append(msg)

    traces = []

    def fake_print_traceback():
        traces.append(True)

    import decman.core.file_manager as fm_mod

    monkeypatch.setattr(fm_mod, "_install_files", failing_install_files)
    monkeypatch.setattr(os, "remove", fake_remove)
    monkeypatch.setattr(output, "print_error", fake_print_error)
    monkeypatch.setattr(output, "print_traceback", fake_print_traceback)

    ok = update_files(
        store=store,
        modules=set(),
        files={"/etc/app/broken.conf": DummyFile()},
        directories={},
        symlinks={},
        dry_run=False,
    )

    assert ok is False

    # Store unchanged
    assert store["all_files"] == ["/etc/app/keep.conf"]

    # No deletions attempted
    assert removed == []

    # Error and traceback were logged
    assert error_msgs
    assert traces


# symlinks


def test_install_symlinks_creates_missing_link_and_parents(tmp_path):
    target = tmp_path / "target"
    target.write_text("x")

    link = tmp_path / "a" / "b" / "link"

    checked, changed = _install_symlinks({str(link): str(target)}, dry_run=False)

    assert checked == [str(link)]
    assert changed == [str(link)]
    assert link.is_symlink()
    assert os.readlink(link) == str(target)


def test_install_symlinks_no_change_when_already_points_to_target(tmp_path):
    target = tmp_path / "target"
    target.write_text("x")

    link = tmp_path / "link"
    os.symlink(str(target), str(link))

    checked, changed = _install_symlinks({str(link): str(target)}, dry_run=False)

    assert checked == [str(link)]
    assert changed == []
    assert link.is_symlink()
    assert os.readlink(link) == str(target)


def test_install_symlinks_replaces_wrong_target(tmp_path):
    target1 = tmp_path / "target1"
    target2 = tmp_path / "target2"
    target1.write_text("1")
    target2.write_text("2")

    link = tmp_path / "link"
    os.symlink(str(target1), str(link))

    checked, changed = _install_symlinks({str(link): str(target2)}, dry_run=False)

    assert checked == [str(link)]
    assert changed == [str(link)]
    assert link.is_symlink()
    assert os.readlink(link) == str(target2)


def test_install_symlinks_replaces_existing_regular_file(tmp_path):
    target = tmp_path / "target"
    target.write_text("x")

    link = tmp_path / "link"
    link.write_text("not a symlink")

    checked, changed = _install_symlinks({str(link): str(target)}, dry_run=False)

    assert checked == [str(link)]
    assert changed == [str(link)]
    assert link.is_symlink()
    assert os.readlink(link) == str(target)


def test_install_symlinks_dry_run_does_not_touch_fs(tmp_path):
    target = tmp_path / "target"
    target.write_text("x")

    link = tmp_path / "a" / "b" / "link"

    checked, changed = _install_symlinks({str(link): str(target)}, dry_run=True)

    assert checked == [str(link)]
    assert changed == [str(link)]  # would change
    assert not link.exists()


def test_update_files_tracks_symlinks_and_removes_stale_symlinks(tmp_path):
    # layout
    root = tmp_path
    t = root / "target"
    t.write_text("x")

    live_link = root / "links" / "live"
    stale_link = root / "links" / "stale"

    # pre-existing stale link to be removed
    os.makedirs(stale_link.parent, exist_ok=True)
    os.symlink(str(t), str(stale_link))

    m = DummyModule(
        name="mod1",
        file_map={},
        dir_map={},
        symlink_map={str(live_link): str(t)},
    )

    store = DummyStore(
        {"all_files": [str(stale_link)]}  # new store key
    )

    ok = update_files(
        store=store,
        modules={m},
        files={},
        directories={},
        symlinks={},
        dry_run=False,
    )

    assert ok is True

    # new link exists
    assert live_link.is_symlink()
    assert os.readlink(live_link) == str(t)

    # stale link removed
    assert not stale_link.exists()

    # store updated
    assert store["all_files"] == [str(live_link)]


def test_update_files_dry_run_does_not_create_or_remove_symlinks(tmp_path):
    root = tmp_path
    t = root / "target"
    t.write_text("x")

    live_link = root / "links" / "live"
    stale_link = root / "links" / "stale"

    os.makedirs(stale_link.parent, exist_ok=True)
    os.symlink(str(t), str(stale_link))

    m = DummyModule(
        name="mod1",
        file_map={},
        dir_map={},
        symlink_map={str(live_link): str(t)},
    )

    store = DummyStore({"all_files": [str(stale_link)]})

    ok = update_files(
        store=store,
        modules={m},
        files={},
        directories={},
        symlinks={},
        dry_run=True,
    )

    assert ok is True

    # no fs changes
    assert not live_link.exists()
    assert stale_link.is_symlink()

    # store unchanged
    assert store["all_files"] == [str(stale_link)]
