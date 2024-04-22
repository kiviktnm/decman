# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring

import unittest
from decman.lib import UserFacingError, Pacman, Store
from decman.lib.aur import ForeignPackageManager, DepTreeNode, ForeignPackage, ExtendedPackageSearch


class TestAUR(unittest.TestCase):

    def setUp(self) -> None:
        self.aur = ForeignPackageManager(Store(), Pacman(),
                                         ExtendedPackageSearch())

    def test_should_upgrade_package_returns_true_on_newer_version(self):
        self.assertTrue(
            self.aur.should_upgrade_package("test", "0.1.9", "0.2.0"))

    def test_should_upgrade_package_returns_false_on_older_version(self):
        self.assertFalse(
            self.aur.should_upgrade_package("test", "0.1.9", "0.1.8"))

    def test_should_upgrade_package_returns_false_on_same_version(self):
        self.assertFalse(
            self.aur.should_upgrade_package("test", "0.1.9", "0.1.9"))

    def test_should_upgrade_package_returns_true_on_devel(self):
        self.assertTrue(
            self.aur.should_upgrade_package("test-git",
                                            "0",
                                            "0",
                                            upgrade_devel=True))


class TestDepTree(unittest.TestCase):

    def test_add_dependency(self):
        root = DepTreeNode("", None)

        root.add_dependency_package("A", [])
        root.add_dependency_package("B", ["A"])
        root.add_dependency_package("B1", ["A"])
        root.add_dependency_package("C", ["B", "A"])

        self.assertIn("A", root.children)
        self.assertIn("B", root.children["A"].children)
        self.assertIn("B1", root.children["A"].children)
        self.assertIn("C", root.children["A"].children["B"].children)

    def test_cyclic_dep_fails(self):
        root = DepTreeNode("", None)

        root.add_dependency_package("A", [])
        root.add_dependency_package("B", ["A"])

        with self.assertRaises(UserFacingError):
            root.add_dependency_package("A", ["B", "A"])

    def test_get_and_remove_outer_deps(self):
        root = DepTreeNode("", None)

        root.add_dependency_package("A", [])
        root.add_dependency_package("B", ["A"])
        root.add_dependency_package("B1", ["A"])
        root.add_dependency_package("C", ["B", "A"])

        a = ForeignPackage("A")
        a.add_foreign_dependency_packages(["B", "B1", "C"])
        b = ForeignPackage("B")
        b.add_foreign_dependency_packages(["C"])
        b1 = ForeignPackage("B1")
        c = ForeignPackage("C")

        self.assertCountEqual(root.get_and_remove_outer_dep_pkgs(), [c, b1])
        self.assertCountEqual(root.get_and_remove_outer_dep_pkgs(), [b])
        self.assertCountEqual(root.get_and_remove_outer_dep_pkgs(), [a])

        last = root.get_and_remove_outer_dep_pkgs()

        self.assertEqual(len(last), 1)
        self.assertEqual(last.pop().name, "")
