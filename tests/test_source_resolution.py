# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring

from typing import override
import unittest

from decman import Module, UserPackage
from decman.lib import Source, Store


class ExistingTestModule(Module):
    def __init__(self):
        self.on_enable_executed = False
        self.on_disable_executed = False
        self.after_update_executed = False
        self.after_version_change_executed = False
        super().__init__("Existing", True, "1")

    def on_enable(self):
        self.on_enable_executed = True

    def on_disable(self):
        self.on_disable_executed = True

    def after_update(self):
        self.after_update_executed = True

    def after_version_change(self):
        self.after_version_change_executed = True


class ExistingChangedVersionTestModule(Module):
    def __init__(self):
        self.on_enable_executed = False
        self.on_disable_executed = False
        self.after_update_executed = False
        self.after_version_change_executed = False
        super().__init__("ExistingChanged", True, "2")

    def on_enable(self):
        self.on_enable_executed = True

    def on_disable(self):
        self.on_disable_executed = True

    def after_update(self):
        self.after_update_executed = True

    def after_version_change(self):
        self.after_version_change_executed = True


class EnabledTestModule(Module):
    def __init__(self):
        self.on_enable_executed = False
        self.on_disable_executed = False
        self.after_update_executed = False
        self.after_version_change_executed = False
        super().__init__("Enabled", True, "1")

    def on_enable(self):
        self.on_enable_executed = True

    def on_disable(self):
        self.on_disable_executed = True

    def after_update(self):
        self.after_update_executed = True

    def after_version_change(self):
        self.after_version_change_executed = True

    def pacman_packages(self) -> list[str]:
        return ["M_p1", "M_p2", "M_p3"]

    def systemd_user_units(self) -> dict[str, list[str]]:
        return {"muser": ["M_u1.service"]}

    def flatpak_packages(self) -> list[str]:
        return ["M_f1", "M_f2"]


class DisabledTestModule(Module):
    def __init__(self):
        self.on_enable_executed = False
        self.on_disable_executed = False
        self.after_update_executed = False
        self.after_version_change_executed = False
        super().__init__("Disabled", False, "1")

    def on_enable(self):
        self.on_enable_executed = True

    def on_disable(self):
        self.on_disable_executed = True

    def after_update(self):
        self.after_update_executed = True

    def after_version_change(self):
        self.after_version_change_executed = True

    def aur_packages(self) -> list[str]:
        return ["M_A1", "M_A2", "M_A3"]

    def systemd_units(self) -> list[str]:
        return ["M_1.service"]


class TestSource(unittest.TestCase):
    def setUp(self):
        self.disabled_module = DisabledTestModule()
        self.enabled_module = EnabledTestModule()
        self.existing_module = ExistingTestModule()
        self.existing_module_changed = ExistingChangedVersionTestModule()
        modules = {
            self.enabled_module,
            self.disabled_module,
            self.existing_module,
            self.existing_module_changed,
        }
        source = Source(
            pacman_packages={"p1", "p2", "p3"},
            aur_packages={"A1", "A2", "A3"},
            user_packages={
                UserPackage(
                    pkgname="U1",
                    version="1",
                    dependencies=["d1"],
                    git_url="/am/url/yes",
                ),
                UserPackage(
                    pkgname="U2",
                    version="1",
                    dependencies=["d2"],
                    git_url="/am/url/yes",
                ),
            },
            ignored_packages={"i1", "i2"},
            systemd_units={"1.service", "2.timer"},
            systemd_user_units={"user": {"u1.service", "u2.timer"}},
            modules=modules,
            files={},
            directories={},
            flatpak_packages={"f1", "f2", "f3"},
            flatpak_user_packages={"fu1", "fu2", "fu3"},
            ignored_flatpak_packages={"i1", "i2"},
        )

        store = Store()
        store.enabled_systemd_units.extend(["1.service", "3.service", "M_1.service"])
        store.add_enabled_user_systemd_unit("user", "u1.service")
        store.add_enabled_user_systemd_unit("user", "u3.service")
        store.enabled_modules = {
            "Existing": "1",
            "ExistingChanged": "1",
            "Disabled": "1",
        }
        store.created_files = ["/test/file1", "/test/file2", "/test/file3"]

        currently_installed_packages = [
            "p1",
            "p2",
            "p4",
            "A2",
            "A3",
            "A4",
            "U1",
            "i1",
            "M_p3",
            "M_A1",
            "M_A2",
        ]

        self.source = source
        self.store = store
        self.currently_installed_packages = currently_installed_packages

    def test_all_enabled_modules(self):
        enabled_modules = [
            ("Enabled", "1"),
            ("Existing", "1"),
            ("ExistingChanged", "2"),
        ]
        self.assertCountEqual(self.source.all_enabled_modules(), enabled_modules)

    def test_files_to_remove(self):
        created_files = ["/test/file1", "/test/file4"]
        self.assertCountEqual(
            self.source.files_to_remove(self.store, created_files),
            ["/test/file2", "/test/file3"],
        )

    def test_after_update_executed(self):
        self.source.run_after_update()

        self.assertTrue(self.enabled_module.after_update_executed)
        self.assertTrue(self.existing_module.after_update_executed)
        self.assertTrue(self.existing_module_changed.after_update_executed)
        self.assertFalse(self.disabled_module.after_update_executed)

    def test_after_version_change_executed(self):
        self.source.run_after_version_change(self.store)

        self.assertTrue(self.enabled_module.after_version_change_executed)
        self.assertTrue(self.existing_module_changed.after_version_change_executed)
        self.assertFalse(self.existing_module.after_version_change_executed)
        self.assertFalse(self.disabled_module.after_version_change_executed)

    def test_on_enable_executed(self):
        self.source.run_on_enable(self.store)

        self.assertTrue(self.enabled_module.on_enable_executed)
        self.assertFalse(self.disabled_module.on_enable_executed)
        self.assertFalse(self.existing_module.on_enable_executed)
        self.assertFalse(self.existing_module_changed.on_enable_executed)

    def test_on_disable_executed(self):
        self.source.run_on_disable(self.store)

        self.assertTrue(self.disabled_module.on_disable_executed)
        self.assertFalse(self.enabled_module.on_disable_executed)
        self.assertFalse(self.existing_module.on_disable_executed)
        self.assertFalse(self.existing_module_changed.on_disable_executed)

    def test_units_to_enable(self):
        self.assertCountEqual(
            self.source.units_to_enable(self.store),
            ["2.timer"],
        )

    def test_units_to_disable(self):
        self.assertCountEqual(
            self.source.units_to_disable(self.store),
            ["3.service", "M_1.service"],
        )

    def test_user_units_to_enable(self):
        self.assertDictEqual(
            self.source.user_units_to_enable(self.store),
            {"user": ["u2.timer"], "muser": ["M_u1.service"]},
        )

    def test_user_units_to_disable(self):
        self.assertDictEqual(
            self.source.user_units_to_disable(self.store),
            {"user": ["u3.service"]},
        )

    def test_pacman_packages_to_install(self):
        self.assertCountEqual(
            self.source.pacman_packages_to_install(self.currently_installed_packages),
            ["p3", "M_p1", "M_p2"],
        )

    def test_foreign_packages_to_install(self):
        self.assertCountEqual(
            self.source.foreign_packages_to_install(self.currently_installed_packages),
            ["A1", "U2"],
        )

    def test_packages_to_remove(self):
        self.assertCountEqual(
            self.source.packages_to_remove(self.currently_installed_packages),
            ["p4", "A4", "M_A1", "M_A2"],
        )


class TestModuleUserServices(unittest.TestCase):
    class ModuleWithUserServiceOne(Module):
        def __init__(self):
            super().__init__("one", True, "0")

        def systemd_user_units(self) -> dict[str, list[str]]:
            return {"user": ["foo.service"]}

    class ModuleWithUserServiceTwo(Module):
        def __init__(self):
            super().__init__("two", True, "0")

        def systemd_user_units(self) -> dict[str, list[str]]:
            return {"user": ["bar.service"]}

    def setUp(self) -> None:
        self.source = Source(
            pacman_packages=set(),
            aur_packages=set(),
            user_packages=set(),
            ignored_packages=set(),
            systemd_units=set(),
            systemd_user_units={},
            files={},
            directories={},
            modules={self.ModuleWithUserServiceOne(), self.ModuleWithUserServiceTwo()},
            flatpak_packages=set(),
            flatpak_user_packages=set(),
            ignored_flatpak_packages=set(),
        )
        self.store = Store()

    def test_user_units_to_enable(self):
        result = self.source.user_units_to_enable(self.store)
        self.assertEqual(len(result), 1)
        self.assertCountEqual(result["user"], ["foo.service", "bar.service"])
