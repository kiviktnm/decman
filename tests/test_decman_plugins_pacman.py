from typing import Any

import pytest

from decman.plugins import pacman as pacman_plugin


class FakeStore(dict):
    def ensure(self, key: str, default: Any) -> None:
        if key not in self:
            self[key] = default


class FakeModule:
    def __init__(self, name: str, packages: set[str]) -> None:
        self.name = name
        self._changed = False
        self._packages = packages


def test_process_modules_collects_packages_and_marks_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pacman = pacman_plugin.Pacman()
    store = FakeStore()
    mod1 = FakeModule("mod1", {"pkg1", "pkg2"})
    mod2 = FakeModule("mod2", {"pkg3"})

    def fake_run_method_with_attribute(mod: FakeModule, attr: str) -> set[str]:
        assert attr == "__pacman__packages__"
        return mod._packages

    monkeypatch.setattr(
        pacman_plugin.plugins,
        "run_method_with_attribute",
        fake_run_method_with_attribute,
    )

    pacman.process_modules(store, {mod1, mod2})

    # packages collected
    assert pacman.packages == {"pkg1", "pkg2", "pkg3"}
    # stored mapping per module
    assert store["packages_for_module"]["mod1"] == {"pkg1", "pkg2"}
    assert store["packages_for_module"]["mod2"] == {"pkg3"}
    # modules marked changed (first run)
    assert mod1._changed is True
    assert mod2._changed is True


def test_apply_dry_run_computes_sets_and_does_not_call_pacman(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pacman = pacman_plugin.Pacman()
    store = FakeStore()

    # Desired state
    pacman.packages = {"keep-explicit", "new-pkg"}

    # Fake PacmanInterface returned by plugin module
    class FakePM:
        def __init__(self, commands, print_highlights, keywords) -> None:  # noqa: D401
            self.commands = commands
            self.print_highlights = print_highlights
            self.keywords = keywords
            self.remove_called_with: set[str] | None = None
            self.set_as_deps_called_with: set[str] | None = None
            self.upgrade_called = False
            self.install_called_with: set[str] | None = None

        def get_native_explicit(self) -> set[str]:
            # keep-explicit (in desired), old-explicit (to demote/remove)
            return {"keep-explicit", "old-explicit"}

        def get_foreign_explicit(self) -> set[str]:
            # foreign-package protects its deps
            return {"foreign-pkg"}

        def get_native_orphans(self) -> set[str]:
            # orphan-explicit is also candidate
            return {"orphan-explicit"}

        def get_dependants(self, pkg: str) -> set[str]:
            # old-explicit has a foreign dependant -> demote to dep
            # orphan-explicit has no dependants -> remove
            if pkg == "old-explicit":
                return {"foreign-pkg"}
            if pkg == "orphan-explicit":
                return set()
            return set()

        def remove(self, pkgs: set[str]) -> None:
            self.remove_called_with = pkgs

        def set_as_dependencies(self, pkgs: set[str]) -> None:
            self.set_as_deps_called_with = pkgs

        def upgrade(self) -> None:
            self.upgrade_called = True

        def install(self, pkgs: set[str]) -> None:
            self.install_called_with = pkgs

    fake_pm = FakePM(None, None, None)

    def fake_pm_ctor(commands, print_highlights, keywords) -> FakePM:
        # constructor used in Pacman.apply
        fake_pm.commands = commands
        fake_pm.print_highlights = print_highlights
        fake_pm.keywords = keywords
        return fake_pm

    monkeypatch.setattr(pacman_plugin, "PacmanInterface", fake_pm_ctor)

    printed_lists: list[tuple[str, list[str]]] = []
    printed_summaries: list[str] = []

    def fake_print_list(title: str, items: list[str]) -> None:
        printed_lists.append((title, items))

    def fake_print_summary(msg: str) -> None:
        printed_summaries.append(msg)

    monkeypatch.setattr(pacman_plugin.output, "print_list", fake_print_list)
    monkeypatch.setattr(pacman_plugin.output, "print_summary", fake_print_summary)

    ok = pacman.apply(store, dry_run=True)

    assert ok is True

    # to_remove = (native | orphans) - desired
    #           = {keep-explicit, old-explicit} ∪ {orphan-explicit} - {keep-explicit, new-pkg}
    #           = {old-explicit, orphan-explicit}
    #
    # old-explicit has foreign dependant -> demoted to dep
    # orphan-explicit has no dependants -> removed

    # printed lists (titles and contents)
    titles = [t for t, _ in printed_lists]
    assert "Removing pacman packages:" in titles
    assert "Setting previously explicitly installed packages as dependencies:" in titles
    assert "Installing pacman packages:" in titles

    # find lists by title
    remove_list = next(items for t, items in printed_lists if "Removing pacman packages:" in t)
    demote_list = next(
        items
        for t, items in printed_lists
        if "Setting previously explicitly installed packages as dependencies:" in t
    )
    install_list = next(items for t, items in printed_lists if "Installing pacman packages:" in t)

    assert remove_list == ["orphan-explicit"]
    assert demote_list == ["old-explicit"]
    # to_install = desired - currently_installed_native
    #            = {keep-explicit, new-pkg} - {keep-explicit, old-explicit}
    #            = {new-pkg}
    assert install_list == ["new-pkg"]

    # Upgrade summary printed even in dry-run
    assert any("Upgrading packages." in s for s in printed_summaries)

    # No mutating calls in dry-run
    assert fake_pm.remove_called_with is None
    assert fake_pm.set_as_deps_called_with is None
    assert fake_pm.upgrade_called is False
    assert fake_pm.install_called_with is None


def test_apply_returns_false_on_command_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    pacman = pacman_plugin.Pacman()
    store = FakeStore()
    pacman.packages = set()

    class FailingPM:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401
            pass

        def get_native_explicit(self) -> set[str]:
            raise pacman_plugin.errors.CommandFailedError(["get_native_explicit"], "boom")

    monkeypatch.setattr(pacman_plugin, "PacmanInterface", FailingPM)

    errors_logged: list[str] = []
    continuations: list[str] = []
    traceback_called = []

    def fake_print_error(msg: str) -> None:
        errors_logged.append(msg)

    def fake_print_continuation(msg: str) -> None:
        continuations.append(msg)

    def fake_print_traceback() -> None:
        traceback_called.append(True)

    monkeypatch.setattr(pacman_plugin.output, "print_error", fake_print_error)
    monkeypatch.setattr(pacman_plugin.output, "print_continuation", fake_print_continuation)
    monkeypatch.setattr(pacman_plugin.output, "print_traceback", fake_print_traceback)

    ok = pacman.apply(store, dry_run=False)

    assert ok is False
    assert any("pacman command failed" in msg for msg in errors_logged)
    assert any("boom" in msg for msg in continuations)
    assert traceback_called  # at least once


def test_ignored_packages_are_not_removed_or_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    pacman = pacman_plugin.Pacman()
    store = FakeStore()

    # Desired state: "already" and "new" should be managed normally.
    # "ignored-installed" is currently installed but not desired -> would normally be removed.
    # "ignored-uninstalled" is desired but not installed -> would normally be installed.
    pacman.packages = {"already", "new", "ignored-uninstalled"}
    pacman.ignored_packages = {"ignored-installed", "ignored-uninstalled"}

    class FakePM:
        def __init__(self, commands, print_highlights, keywords) -> None:
            self.commands = commands
            self.print_highlights = print_highlights
            self.keywords = keywords

            self.remove_called_with: set[str] | None = None
            self.install_called_with: set[str] | None = None
            self.set_as_deps_called_with: set[str] | None = None
            self.upgrade_called = False

        def get_native_explicit(self) -> set[str]:
            # currently installed explicit packages
            return {"ignored-installed", "already"}

        def get_foreign_explicit(self) -> set[str]:
            return set()

        def get_native_orphans(self) -> set[str]:
            return set()

        def get_dependants(self, pkg: str) -> set[str]:
            return set()

        def remove(self, pkgs: set[str]) -> None:
            self.remove_called_with = pkgs

        def set_as_dependencies(self, pkgs: set[str]) -> None:
            self.set_as_deps_called_with = pkgs

        def upgrade(self) -> None:
            self.upgrade_called = True

        def install(self, pkgs: set[str]) -> None:
            self.install_called_with = pkgs

    fake_pm = FakePM(None, None, None)

    def fake_pm_ctor(commands, print_highlights, keywords) -> FakePM:
        fake_pm.commands = commands
        fake_pm.print_highlights = print_highlights
        fake_pm.keywords = keywords
        return fake_pm

    monkeypatch.setattr(pacman_plugin, "PacmanInterface", fake_pm_ctor)

    printed_lists: list[tuple[str, list[str]]] = []

    def fake_print_list(title: str, items: list[str]) -> None:
        printed_lists.append((title, items))

    # don't care about summaries here
    monkeypatch.setattr(pacman_plugin.output, "print_list", fake_print_list)
    monkeypatch.setattr(pacman_plugin.output, "print_summary", lambda *_args, **_kw: None)

    ok = pacman.apply(store, dry_run=False)

    assert ok is True

    # Ignored packages must never be passed to remove() or install()
    assert (
        fake_pm.remove_called_with is None or "ignored-installed" not in fake_pm.remove_called_with
    )
    assert fake_pm.install_called_with is not None
    assert "ignored-uninstalled" not in fake_pm.install_called_with

    # Also ensure the printed install list doesn't contain ignored packages
    install_items = next(
        items for title, items in printed_lists if "Installing pacman packages:" in title
    )
    assert "ignored-uninstalled" not in install_items
    # "new" is the only package that should be installed in this scenario
    assert install_items == ["new"]
