import typing

from decman.plugins.pacman.error import DependencyCycleError


class ForeignPackage:
    """
    Class used to keep track of foreign recursive dependency packages of an foreign package.
    """

    def __init__(self, name: str):
        self.name = name
        self._all_recursive_foreign_deps: set[str] = set()

    def __eq__(self, value: object, /) -> bool:
        if isinstance(value, self.__class__):
            return (
                self.name == value.name
                and self._all_recursive_foreign_deps == value._all_recursive_foreign_deps
            )
        return False

    def __hash__(self) -> int:
        return self.name.__hash__()

    def __repr__(self) -> str:
        return f"{self.name}: {{{' '.join(self._all_recursive_foreign_deps)}}}"

    def __str__(self) -> str:
        return f"{self.name}"

    def add_foreign_dependency_packages(self, package_names: typing.Iterable[str]):
        """
        Adds dependencies to the package.
        """
        self._all_recursive_foreign_deps.update(package_names)

    def get_all_recursive_foreign_dep_pkgs(self) -> set[str]:
        """
        Returns all dependencies and sub-dependencies of the package.
        """
        return set(self._all_recursive_foreign_deps)


class DepNode:
    """
    A Node of the DepGraph
    """

    def __init__(self, package: ForeignPackage) -> None:
        self.parents: dict[str, DepNode] = {}
        self.children: dict[str, DepNode] = {}
        self.pkg = package

    def is_pkgname_in_parents_recursive(self, pkgname: str) -> bool:
        """
        Returns True if the given package name is in the parents of this DepNode.
        """
        for name, parent in self.parents.items():
            if name == pkgname or parent.is_pkgname_in_parents_recursive(pkgname):
                return True
        return False


class DepGraph:
    """
    Represents a graph between foreign packages
    """

    def __init__(self) -> None:
        self.package_nodes: dict[str, DepNode] = {}
        self._childless_node_names: set[str] = set()

    def add_requirement(self, child_pkgname: str, parent_pkgname: typing.Optional[str]):
        """
        Adds a connection between two packages, creating the child package if it doesn't exist.

        The parent is the package that requires the child package.
        """
        child_node = self.package_nodes.get(child_pkgname, DepNode(ForeignPackage(child_pkgname)))
        self.package_nodes[child_pkgname] = child_node

        if len(child_node.children) == 0:
            self._childless_node_names.add(child_pkgname)

        if parent_pkgname is None:
            return

        parent_node = self.package_nodes[parent_pkgname]

        if parent_node.is_pkgname_in_parents_recursive(child_pkgname):
            raise DependencyCycleError(child_pkgname, parent_pkgname)

        parent_node.children[child_pkgname] = child_node
        child_node.parents[parent_pkgname] = parent_node

        if parent_pkgname in self._childless_node_names:
            self._childless_node_names.remove(parent_pkgname)

    def get_and_remove_outer_dep_pkgs(self) -> list[ForeignPackage]:
        """
        Returns all childless nodes of the dependency package graph and removes them.
        """
        new_childless_node_names = set()
        result = []
        for childless_node_name in self._childless_node_names:
            childless_node = self.package_nodes[childless_node_name]

            for parent in childless_node.parents.values():
                new_deps = childless_node.pkg.get_all_recursive_foreign_dep_pkgs()
                new_deps.add(childless_node.pkg.name)
                parent.pkg.add_foreign_dependency_packages(new_deps)
                del parent.children[childless_node_name]
                if len(parent.children) == 0:
                    new_childless_node_names.add(parent.pkg.name)

            result.append(childless_node.pkg)
        self._childless_node_names = new_childless_node_names
        return result
