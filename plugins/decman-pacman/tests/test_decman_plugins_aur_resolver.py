import pytest
from decman.plugins.aur.error import DependencyCycleError
from decman.plugins.aur.resolver import DepGraph, ForeignPackage


def test_add_dependency():
    graph = DepGraph()

    graph.add_requirement("A", None)
    graph.add_requirement("B1", "A")
    graph.add_requirement("B2", "A")
    graph.add_requirement("C", "B1")

    assert "B1" in graph.package_nodes["A"].children
    assert "B2" in graph.package_nodes["A"].children
    assert "C" in graph.package_nodes["B1"].children


def test_cyclic_dependency_raises():
    graph = DepGraph()

    graph.add_requirement("A", None)
    graph.add_requirement("B", "A")
    graph.add_requirement("C", "B")

    with pytest.raises(DependencyCycleError):
        graph.add_requirement("A", "C")


def _build_graph_for_outer_deps() -> DepGraph:
    graph = DepGraph()

    # Roots
    graph.add_requirement("A", None)
    graph.add_requirement("V", None)

    # Level B
    graph.add_requirement("B1", "A")
    graph.add_requirement("B2", "A")
    graph.add_requirement("B3", "A")

    # Extra dependency B1 -> B2
    graph.add_requirement("B1", "B2")

    # Level C
    graph.add_requirement("C1", "B1")
    graph.add_requirement("C2", "B1")

    # Level D + cycle-ish edges
    graph.add_requirement("D", "C1")
    graph.add_requirement("C2", "D")

    # Foreign packages and their foreign deps
    defs = {
        "V": [],
        "A": ["B1", "B2", "B3", "C1", "C2", "D"],
        "B1": ["C1", "C2", "D"],
        "B2": ["B1", "C1", "C2", "D"],
        "B3": [],
        "C1": ["D", "C2"],
        "C2": [],
        "D": ["C2"],
    }

    for name, deps in defs.items():
        pkg = ForeignPackage(name)
        pkg.add_foreign_dependency_packages(deps)

    return graph


def _assert_outer_dep_names(graph: DepGraph, expected: set[str]) -> None:
    result = graph.get_and_remove_outer_dep_pkgs()
    names = {pkg.name for pkg in result}
    assert names == expected


def test_get_and_remove_outer_deps_sequence():
    graph = _build_graph_for_outer_deps()

    _assert_outer_dep_names(graph, {"C2", "B3", "V"})
    _assert_outer_dep_names(graph, {"D"})
    _assert_outer_dep_names(graph, {"C1"})
    _assert_outer_dep_names(graph, {"B1"})
    _assert_outer_dep_names(graph, {"B2"})
    _assert_outer_dep_names(graph, {"A"})
    _assert_outer_dep_names(graph, set())
