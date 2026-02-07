from typing import Any

import pytest

from decman.plugins import aur as aur_plugin


class FakeStore(dict):
    def ensure(self, key: str, default: Any) -> None:
        if key not in self:
            self[key] = default


class FakeModule:
    def __init__(self, name: str, aur_pkgs: set[str], custom_pkgs: set[Any]) -> None:
        self.name = name
        self._changed = False
        self._aur_pkgs = aur_pkgs
        self._custom_pkgs = custom_pkgs


class FakeCustomPackage:
    def __init__(self, pkgname: str) -> None:
        self.pkgname = pkgname

    def __hash__(self) -> int:  # needed because instances go into sets
        return hash(self.pkgname)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeCustomPackage) and self.pkgname == other.pkgname

    def parse(self, commands: Any) -> str:
        # Whatever ForeignPackageManager expects; we just need something to feed into add_custom_pkg
        return f"parsed-{self.pkgname}"


def test_process_modules_collects_aur_and_custom_packages_and_marks_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aur = aur_plugin.AUR()
    store = FakeStore()

    cp1 = FakeCustomPackage("custom1")
    cp2 = FakeCustomPackage("custom2")

    mod1 = FakeModule("mod1", {"aur1", "aur2"}, {cp1})
    mod2 = FakeModule("mod2", {"aur3"}, {cp2})

    def fake_run_method_with_attribute(mod: FakeModule, attr: str):
        if attr == "__aur__packages__":
            return mod._aur_pkgs
        if attr == "__custom__packages__":
            return mod._custom_pkgs
        return None

    monkeypatch.setattr(
        aur_plugin.plugins, "run_method_with_attribute", fake_run_method_with_attribute
    )

    aur.process_modules(store, {mod1, mod2})

    # union of all aur/custom packages collected
    assert aur.packages == {"aur1", "aur2", "aur3"}
    assert aur.custom_packages == {cp1, cp2}

    # stored per-module
    assert store["aur_packages_for_module"]["mod1"] == {"aur1", "aur2"}
    assert store["aur_packages_for_module"]["mod2"] == {"aur3"}
    assert store["custom_packages_for_module"]["mod1"] == {str(cp1)}
    assert store["custom_packages_for_module"]["mod2"] == {str(cp2)}

    # first run: modules marked changed
    assert mod1._changed is True
    assert mod2._changed is True


def test_apply_respects_ignored_packages_and_protects_their_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aur = aur_plugin.AUR()
    store = FakeStore()

    # Desired AUR/custom state
    aur.packages = {"desired-aur"}
    cp = FakeCustomPackage("custom-aur")
    aur.custom_packages = {cp}

    # Ignored foreign package (installed) and an ignored but *uninstalled* package
    aur.ignored_packages = {"ignored-aur", "ignored-not-installed"}

    # Fake PackageSearch
    class FakePackageSearch:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
            self.added: list[Any] = []

        def add_custom_pkg(self, parsed: Any) -> None:
            self.added.append(parsed)

    monkeypatch.setattr(aur_plugin, "PackageSearch", FakePackageSearch)
    monkeypatch.setattr(aur_plugin.os, "makedirs", lambda *x, **kw: None)

    # Fake pacman interface for foreign/native info
    class FakePM:
        def __init__(self, commands, print_highlights, keywords, dbsiglevel, dbpath) -> None:
            self.commands = commands
            self.print_highlights = print_highlights
            self.keywords = keywords

            self.remove_called_with: set[str] | None = None
            self.set_as_deps_called_with: set[str] | None = None

        def get_native_explicit(self) -> set[str]:
            # no natives needed for this scenario
            return set()

        def get_foreign_explicit(self) -> set[str]:
            # All explicitly installed foreign packages:
            # - ignored-aur           (ignored, must stay and protect deps)
            # - dep-of-ignored        (candidate; has ignored dependant)
            # - orphan-foreign        (candidate; no dependants)
            return {"ignored-aur", "dep-of-ignored", "orphan-foreign"}

        def get_foreign_orphans(self) -> set[str]:
            # orphan-foreign also considered orphan
            return {"orphan-foreign"}

        def get_dependants(self, pkg: str) -> set[str]:
            if pkg == "dep-of-ignored":
                # ignored-aur depends on dep-of-ignored -> must demote, not remove
                return {"ignored-aur"}
            if pkg == "orphan-foreign":
                return set()
            return set()

        def remove(self, pkgs: set[str]) -> None:
            self.remove_called_with = pkgs

        def set_as_dependencies(self, pkgs: set[str]) -> None:
            self.set_as_deps_called_with = pkgs

    fake_pm = FakePM(None, None, None, None, None)

    def fake_pm_ctor(
        commands,
        print_highlights,
        keywords,
        dbsiglevel,
        dbpath,
    ) -> FakePM:
        fake_pm.commands = commands
        fake_pm.print_highlights = print_highlights
        fake_pm.keywords = keywords
        return fake_pm

    monkeypatch.setattr(aur_plugin, "AurPacmanInterface", fake_pm_ctor)

    # Fake ForeignPackageManager
    class FakeFPM:
        def __init__(
            self,
            store_arg,
            pm_arg,
            package_search_arg,
            commands_arg,
            cache_dir,
            build_dir,
            makepkg_user,
        ) -> None:
            self.store = store_arg
            self.pm = pm_arg
            self.package_search = package_search_arg
            self.commands = commands_arg
            self.cache_dir = cache_dir
            self.build_dir = build_dir
            self.makepkg_user = makepkg_user

            self.upgrade_args: tuple[bool, bool, set[str]] | None = None
            self.install_called_with: list[str] | None = None

        def upgrade(self, upgrade_devel: bool, force: bool, ignored: set[str]) -> None:
            self.upgrade_args = (upgrade_devel, force, ignored)

        def install(self, pkgs: list[str], force: bool = False) -> None:
            # store as set to ignore ordering
            self.install_called_with = pkgs

    fake_fpm = FakeFPM(None, None, None, None, None, None, None)

    def fake_fpm_ctor(
        store_arg,
        pm_arg,
        package_search_arg,
        commands_arg,
        cache_dir,
        build_dir,
        makepkg_user,
    ):
        fake_fpm.store = store_arg
        fake_fpm.pm = pm_arg
        fake_fpm.package_search = package_search_arg
        fake_fpm.commands = commands_arg
        fake_fpm.cache_dir = cache_dir
        fake_fpm.build_dir = build_dir
        fake_fpm.makepkg_user = makepkg_user
        return fake_fpm

    monkeypatch.setattr(aur_plugin, "ForeignPackageManager", fake_fpm_ctor)

    printed_lists: list[tuple[str, list[str]]] = []
    printed_summaries: list[str] = []

    def fake_print_list(title: str, items: list[str]) -> None:
        printed_lists.append((title, items))

    def fake_print_summary(msg: str) -> None:
        printed_summaries.append(msg)

    monkeypatch.setattr(aur_plugin.output, "print_list", fake_print_list)
    monkeypatch.setattr(aur_plugin.output, "print_summary", fake_print_summary)

    # Use params to test flag propagation into upgrade/install
    ok = aur.apply(store, dry_run=False, params=["aur-upgrade-devel", "aur-force"])

    assert ok is True

    # Removal / demotion logic:
    #
    # custom_package_names = {"custom-aur"}
    # currently_installed_foreign = {"ignored-aur", "dep-of-ignored", "orphan-foreign"}
    # orphans = {"orphan-foreign"}
    #
    # to_remove candidates:
    #   (foreign | orphans) - desired - custom - ignored
    # = {"ignored-aur", "dep-of-ignored", "orphan-foreign"} ∪ {"orphan-foreign"}
    #   - {"desired-aur"} - {"custom-aur"} - {"ignored-aur"}
    # = {"dep-of-ignored", "orphan-foreign"}
    #
    # dependants_to_keep includes ignored installed foreign -> dep-of-ignored is demoted, orphan-foreign removed.

    assert fake_pm.remove_called_with == {"orphan-foreign"}
    assert fake_pm.set_as_deps_called_with == {"dep-of-ignored"}

    # Ensure ignored packages were not removed
    assert "ignored-aur" not in (fake_pm.remove_called_with or set())

    # Upgrade called with flags and ignored set
    assert fake_fpm.upgrade_args == (
        True,
        True,
        aur.ignored_packages | (fake_pm.remove_called_with or set()),
    )

    # to_install = (packages | custom_names) - installed_foreign - ignored
    #            = {"desired-aur", "custom-aur"} - {"ignored-aur", "dep-of-ignored", "orphan-foreign"}
    #              - {"ignored-aur", "ignored-not-installed"}
    #            = {"desired-aur", "custom-aur"}
    assert set(fake_fpm.install_called_with or []) == {"desired-aur", "custom-aur"}
    # ignored packages must not be installed
    assert "ignored-aur" not in (fake_fpm.install_called_with or [])
    assert "ignored-not-installed" not in (fake_fpm.install_called_with or [])

    # Also check the printed lists mirror this
    titles = [t for t, _ in printed_lists]
    assert "Removing foreign packages:" in titles
    assert "Setting previously explicitly installed foreign packages as dependencies:" in titles
    assert "Installing foreign packages:" in titles

    remove_list = next(items for t, items in printed_lists if "Removing foreign packages:" in t)
    demote_list = next(
        items
        for t, items in printed_lists
        if "Setting previously explicitly installed foreign packages as dependencies:" in t
    )
    install_list = next(items for t, items in printed_lists if "Installing foreign packages:" in t)

    assert remove_list == ["orphan-foreign"]
    assert demote_list == ["dep-of-ignored"]
    # Order of install_list is deterministic because sorted() is used
    assert install_list == ["custom-aur", "desired-aur"]
    assert any("Upgrading foreign packages." in s for s in printed_summaries)


def test_apply_returns_false_on_aur_rpc_error(monkeypatch: pytest.MonkeyPatch) -> None:
    aur = aur_plugin.AUR()
    store = FakeStore()

    # Force PackageSearch to fail immediately
    class FailingPackageSearch:
        def __init__(self, timeout: int) -> None:
            raise aur_plugin.AurRPCError("RPC down", "url")

    monkeypatch.setattr(aur_plugin, "PackageSearch", FailingPackageSearch)
    monkeypatch.setattr(aur_plugin.os, "makedirs", lambda *x, **kw: None)

    errors_logged: list[str] = []
    continuations: list[str] = []
    traceback_called: list[bool] = []

    def fake_print_error(msg: str) -> None:
        errors_logged.append(msg)

    def fake_print_traceback() -> None:
        traceback_called.append(True)

    monkeypatch.setattr(aur_plugin.output, "print_error", fake_print_error)
    monkeypatch.setattr(aur_plugin.output, "print_traceback", fake_print_traceback)

    ok = aur.apply(store, dry_run=False)

    assert ok is False
    assert any("AUR RPC" in msg or "fetch data from AUR RPC" in msg for msg in errors_logged)
    assert any("RPC down" in msg for msg in errors_logged)
    assert traceback_called
