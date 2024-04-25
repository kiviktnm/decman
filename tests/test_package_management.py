# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring

import unittest
from decman.error import UserFacingError
from decman.lib import Pacman, Store
from decman.lib.aur import ForeignPackageManager, DepGraph, ForeignPackage, ExtendedPackageSearch


class TestVersionComparisons(unittest.TestCase):

    def setUp(self):
        pacman = Pacman()
        self.aur = ForeignPackageManager(Store(), pacman,
                                         ExtendedPackageSearch(pacman))

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


class TestDepGraph(unittest.TestCase):

    def test_add_dependency(self):
        graph = DepGraph()

        graph.add_requirement("A", None)
        graph.add_requirement("B1", "A")
        graph.add_requirement("B2", "A")
        graph.add_requirement("C", "B1")

        self.assertIn("B1", graph.package_nodes["A"].children)
        self.assertIn("B2", graph.package_nodes["A"].children)
        self.assertIn("C", graph.package_nodes["B1"].children)

    def test_cyclic_dep_fails(self):
        graph = DepGraph()

        graph.add_requirement("A", None)
        graph.add_requirement("B", "A")
        graph.add_requirement("C", "B")

        with self.assertRaises(UserFacingError):
            graph.add_requirement("A", "C")

    def test_get_and_remove_outer_deps(self):
        graph = DepGraph()

        graph.add_requirement("A", None)
        graph.add_requirement("V", None)

        graph.add_requirement("B1", "A")
        graph.add_requirement("B2", "A")
        graph.add_requirement("B3", "A")

        graph.add_requirement("B1", "B2")
        graph.add_requirement("C1", "B1")
        graph.add_requirement("C2", "B1")

        graph.add_requirement("D", "C1")

        graph.add_requirement("C2", "D")

        v = ForeignPackage("V")

        a = ForeignPackage("A")
        a.add_foreign_dependency_packages(["B1", "B2", "B3", "C1", "C2", "D"])

        b1 = ForeignPackage("B1")
        b1.add_foreign_dependency_packages(["C1", "C2", "D"])

        b2 = ForeignPackage("B2")
        b2.add_foreign_dependency_packages(["B1", "C1", "C2", "D"])

        b3 = ForeignPackage("B3")

        c1 = ForeignPackage("C1")
        c1.add_foreign_dependency_packages(["D", "C2"])

        c2 = ForeignPackage("C2")

        d = ForeignPackage("D")
        d.add_foreign_dependency_packages(["C2"])

        self.assertCountEqual(graph.get_and_remove_outer_dep_pkgs(),
                              [c2, b3, v])
        self.assertCountEqual(graph.get_and_remove_outer_dep_pkgs(), [d])
        self.assertCountEqual(graph.get_and_remove_outer_dep_pkgs(), [c1])
        self.assertCountEqual(graph.get_and_remove_outer_dep_pkgs(), [b1])
        self.assertCountEqual(graph.get_and_remove_outer_dep_pkgs(), [b2])
        self.assertCountEqual(graph.get_and_remove_outer_dep_pkgs(), [a])
        self.assertCountEqual(graph.get_and_remove_outer_dep_pkgs(), [])
