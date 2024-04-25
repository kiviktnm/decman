# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring

import unittest
from decman.lib import Source, Store
from decman import UserPackage


class TestSource(unittest.TestCase):

    def setUp(self):
        source = Source(
            pacman_packages=["p1", "p2", "p3"],
            aur_packages=["A1", "A2", "A3"],
            user_packages=[
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
                )
            ],
            ignored_packages=["i1", "i2"],
            systemd_units=["1.service", "2.timer"],
            systemd_user_units={"user": ["u1.service", "u2.timer"]},
        )

        store = Store()
        store.enabled_systemd_units.extend(["1.service", "3.service"])
        store.enabled_user_systemd_units.extend(
            ["user: u1.service", "user: u3.service"])

        currently_installed_packages = [
            "p1",
            "p2",
            "p4",
            "A2",
            "A3",
            "A4",
            "U1",
            "i1",
        ]

        self.source = source
        self.store = store
        self.currently_installed_packages = currently_installed_packages

    def test_units_to_enable(self):
        self.assertCountEqual(
            self.source.units_to_enable(self.store),
            ["2.timer"],
        )

    def test_units_to_disable(self):
        self.assertCountEqual(
            self.source.units_to_disable(self.store),
            ["3.service"],
        )

    def test_user_units_to_enable(self):
        self.assertDictEqual(
            self.source.user_units_to_enable(self.store),
            {"user": ["u2.timer"]},
        )

    def test_user_units_to_disable(self):
        self.assertDictEqual(
            self.source.user_units_to_disable(self.store),
            {"user": ["u3.service"]},
        )

    def test_pacman_packages_to_install(self):
        self.assertCountEqual(
            self.source.pacman_packages_to_install(
                self.currently_installed_packages),
            ["p3"],
        )

    def test_foreign_packages_to_install(self):
        self.assertCountEqual(
            self.source.foreign_packages_to_install(
                self.currently_installed_packages),
            ["A1", "U2"],
        )

    def test_packages_to_remove(self):
        self.assertCountEqual(
            self.source.packages_to_remove(self.currently_installed_packages),
            ["p4", "A4"],
        )
