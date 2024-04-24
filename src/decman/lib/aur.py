"""
Module for interacting with the AUR.

Optional dependencies are ignored when installing AUR packages.

Terminology:

- package (pkg): name of an package from pacman repos or AUR
- dependency (dep): (virtual) package required when building and running a package
- dependency package (dep pkg): dependency that has been resolved to a package name
- all dependencies: normal dependencies and build dependencies combined
"""

import shutil
import subprocess
import os
import re
import typing

import requests

import decman.config as conf
import decman.lib as l


def strip_dependency(dep: str) -> str:
    """
    Removes version spefications from a dependency name.
    """
    rx = re.compile("(=.*|>.*|<.*)")
    return rx.sub("", dep)


def is_devel(package: str) -> bool:
    """
    Returns True if the given package is a devel package.
    """
    devel_suffixes = [
        "-git",
        "-hg",
        "-bzr",
        "-svn",
        "-cvs",
        "-darcs",
    ]
    for suffix in devel_suffixes:
        if package.endswith(suffix):
            return True
    return False


class PackageInfo:
    """
    Simplified information about an package.

    In case of AUR packages, these are fetched from AUR RPC.
    """

    def __init__(self, pkgname: str, pkgbase: str, version: str,
                 provides: list[str], dependencies: list[str],
                 make_dependencies: list[str], check_dependencies: list[str],
                 git_url: str, pacman: l.Pacman):
        self.pkgname = pkgname
        self.pkgbase = pkgbase
        self.version = version
        self.provides = provides
        self.git_url = git_url

        self.foreign_dependencies_stripped = []
        self.foreign_make_dependencies_stripped = []
        self.foreign_check_dependencies_stripped = []
        self.pacman_dependencies = []
        self.pacman_make_dependencies = []
        self.pacman_check_dependencies = []

        for dep in dependencies:
            if pacman.is_installable(dep):
                self.pacman_dependencies.append(dep)
            else:
                self.foreign_dependencies_stripped.append(
                    strip_dependency(dep))

        for make_dep in make_dependencies:
            if pacman.is_installable(make_dep):
                self.pacman_make_dependencies.append(make_dep)
            else:
                self.foreign_make_dependencies_stripped.append(
                    strip_dependency(make_dep))

        for check_dep in check_dependencies:
            if pacman.is_installable(check_dep):
                self.pacman_check_dependencies.append(check_dep)
            else:
                self.foreign_check_dependencies_stripped.append(
                    strip_dependency(check_dep))

    def pkg_file_prefix(self) -> str:
        """
        Returns the beginning of the file created from building this package.
        """
        return f"{self.pkgname}-{self.version}"


class ForeignPackage:
    """
    Class used to keep track of AUR/user recursive dependency packages of an AUR/user package.
    """

    def __init__(self, name: str):
        self.name = name
        self._all_recursive_foreign_deps = set()

    def __eq__(self, value: object, /) -> bool:
        if isinstance(value, self.__class__):
            return self.name == value.name \
                   and self._all_recursive_foreign_deps == value._all_recursive_foreign_deps
        return False

    def __hash__(self) -> int:
        return self.name.__hash__()

    def __repr__(self) -> str:
        return f"{self.name}: {{{' '.join(self._all_recursive_foreign_deps)}}}"

    def __str__(self) -> str:
        return f"{self.name}"

    def add_foreign_dependency_packages(self,
                                        package_names: typing.Iterable[str]):
        """
        Adds dependencies to the package.
        """
        self._all_recursive_foreign_deps.update(package_names)

    def get_all_recursive_foreign_deps(self) -> set[str]:
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
            if name == pkgname or parent.is_pkgname_in_parents_recursive(
                    pkgname):
                return True
        return False


class DepGraph:
    """
    Represents a graph between foreign packages
    """

    def __init__(self):
        self.package_nodes: dict[str, DepNode] = {}
        self._childless_node_names = set()

    def add_requirement(self, child_pkgname: str,
                        parent_pkgname: typing.Optional[str]):
        """
        Adds a connection between two packages, creating the child package if it doesn't exist.

        The parent is the package that requires the child package.
        """
        child_node = self.package_nodes.get(
            child_pkgname, DepNode(ForeignPackage(child_pkgname)))
        self.package_nodes[child_pkgname] = child_node

        if len(child_node.children) == 0:
            self._childless_node_names.add(child_pkgname)

        if parent_pkgname is None:
            return

        parent_node = self.package_nodes[parent_pkgname]

        if parent_node.is_pkgname_in_parents_recursive(child_pkgname):
            raise l.UserFacingError(
                f"Foreign package dependency cycle detected involving '{child_pkgname}' \
and '{parent_pkgname}'. Foreign package dependencies are also required \
during package building and therefore dependency cycles cannot be handled.")

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
                new_deps = childless_node.pkg.get_all_recursive_foreign_deps()
                new_deps.add(childless_node.pkg.name)
                parent.pkg.add_foreign_dependency_packages(new_deps)
                del parent.children[childless_node_name]
                if len(parent.children) == 0:
                    new_childless_node_names.add(parent.pkg.name)

            result.append(childless_node.pkg)
        self._childless_node_names = new_childless_node_names
        return result


class ExtendedPackageSearch:
    """
    Allows searcing for packages / providers from the AUR as well as user defined sources.

    Results are cached and user defined packages are preferred.
    """

    def __init__(self, pacman: l.Pacman):
        self._pacman = pacman
        self._package_info_cache: dict[str, PackageInfo] = {}
        self._dep_provider_cache: dict[str, PackageInfo] = {}
        self._user_packages: list[PackageInfo] = []

    def add_user_pkg(self, user_pkg: PackageInfo):
        """
        Adds the given package to user packages.
        """
        self._user_packages.append(user_pkg)

    def try_caching_packages(self, packages: list[str]):
        """
        Tried caching the given packages. Virtual packages may not be cached
        """

        packages = list(
            filter(lambda p: p not in self._package_info_cache, packages))

        if len(packages) == 0:
            return

        l.print_debug(f"Trying to cache {packages}.")

        max_pkgs_per_request = 200

        while packages:
            to_request = map(lambda p: f"arg[]={p}",
                             packages[:max_pkgs_per_request])
            packages = packages[max_pkgs_per_request:]

            url = f"https://aur.archlinux.org/rpc/v5/info?{'&'.join(to_request)}"
            l.print_debug(f"Request URL = {url}")

            try:
                request = requests.get(url, timeout=conf.aur_rpc_timeout)
                d = request.json()

                if d["type"] == "error":
                    raise l.UserFacingError(
                        f"AUR RPC returned error: {d['error']}")

                for result in d["results"]:
                    pkgname = result["Name"]

                    if pkgname in self._package_info_cache:
                        continue

                    for user_package in self._user_packages:
                        if user_package.pkgname == pkgname:
                            l.print_debug(
                                f"'{pkgname}' found in user packages.")
                            self._package_info_cache[pkgname] = user_package
                            break
                    else:  # if not in user_packages then:
                        info = PackageInfo(
                            pkgname=result["Name"],
                            pkgbase=result["PackageBase"],
                            version=result["Version"],
                            dependencies=result.get("Depends", []),
                            make_dependencies=result.get("MakeDepends", []),
                            check_dependencies=result.get("CheckDepends", []),
                            provides=result.get("Provides", []),
                            git_url=
                            f"https://aur.archlinux.org/{result['PackageBase']}.git",
                            pacman=self._pacman)
                        self._package_info_cache[pkgname] = info

                l.print_debug("Request completed.")
            except (requests.RequestException, KeyError) as e:
                raise l.UserFacingError(
                    "Failed to fetch package information from AUR RPC.") from e

    def get_package_info(self, package: str) -> typing.Optional[PackageInfo]:
        """
        Returns information about a package.

        If the package is not user defined, fetches information from the AUR.
        Returns None if no such AUR package exists.
        """
        l.print_debug(f"Getting new info for package '{package}'.")

        if package in self._package_info_cache:
            l.print_debug(f"'{package}' found in cache.")
            return self._package_info_cache[package]

        for user_package in self._user_packages:
            if user_package.pkgname == package:
                l.print_debug(f"'{package}' found in user packages.")
                self._package_info_cache[package] = user_package
                return user_package

        url = f"https://aur.archlinux.org/rpc/v5/info/{package}"
        l.print_debug(f"Requesting info for '{package}' from AUR. URL = {url}")
        try:
            request = requests.get(url, timeout=conf.aur_rpc_timeout)
            d = request.json()

            if d["type"] == "error":
                raise l.UserFacingError(
                    f"AUR RPC returned error: {d['error']}")

            if d["resultcount"] == 0:
                l.print_debug(f"'{package}' not found.")
                return None

            l.print_debug(f"'{package}' found from AUR.")

            result = d["results"][0]
            info = PackageInfo(
                pkgname=result["Name"],
                pkgbase=result["PackageBase"],
                version=result["Version"],
                dependencies=result.get("Depends", []),
                make_dependencies=result.get("MakeDepends", []),
                check_dependencies=result.get("CheckDepends", []),
                provides=result.get("Provides", []),
                git_url=
                f"https://aur.archlinux.org/{result['PackageBase']}.git",
                pacman=self._pacman)

            self._package_info_cache[package] = info

            return info
        except (requests.RequestException, KeyError) as e:
            raise l.UserFacingError(
                "Failed to fetch package information from AUR RPC.") from e

    def find_provider(
            self, stripped_dependency: str) -> typing.Optional[PackageInfo]:
        """
        Finds a provider for a dependency.

        May prompt the user to select if multiple are available.
        """
        l.print_debug(f"Finding provider for '{stripped_dependency}'.")

        if stripped_dependency in self._dep_provider_cache:
            l.print_debug(f"'{stripped_dependency}' found in cache.")
            return self._dep_provider_cache[stripped_dependency]

        l.print_debug("Are there exact name matches?")

        exact_name_match = self.get_package_info(stripped_dependency)

        if exact_name_match is not None:
            l.print_debug("Exact name match found.")
            self._dep_provider_cache[stripped_dependency] = exact_name_match
            return exact_name_match

        l.print_debug("No exact name matches found. Finding providers.")

        user_pkg_results = []
        for user_package in self._user_packages:
            if stripped_dependency in user_package.provides:
                user_pkg_results.append(user_package.pkgname)

        if len(user_pkg_results) == 1:
            pkg = self.get_package_info(user_pkg_results[0])
            assert pkg is not None
            l.print_debug(
                f"Single provider for '{stripped_dependency}' found in user packages: '{pkg}'."
            )
            self._dep_provider_cache[stripped_dependency] = pkg
            return pkg

        if len(user_pkg_results) > 1:
            return self._choose_provider(stripped_dependency, user_pkg_results,
                                         "user packages")

        url = f"https://aur.archlinux.org/rpc/v5/search/{stripped_dependency}?by=provides"
        l.print_debug(
            f"Requesting providers for '{stripped_dependency}' from AUR. URL = {url}"
        )
        try:
            request = requests.get(url, timeout=conf.aur_rpc_timeout)
            d = request.json()

            if d["type"] == "error":
                raise l.UserFacingError(
                    f"AUR RPC returned error: {d['error']}")

            if d["resultcount"] == 0:
                l.print_debug(f"'{stripped_dependency}' not found.")
                return None

            results = list(map(lambda r: r["Name"], d["results"]))

            if len(results) == 1:
                pkgname = results[0]
                l.print_debug(
                    f"Single provider for '{stripped_dependency}' found from AUR: '{pkgname}'"
                )
                info = self.get_package_info(pkgname)
                return info

            return self._choose_provider(stripped_dependency, results, "AUR")
        except (requests.RequestException, KeyError) as e:
            raise l.UserFacingError(
                "Failed to fetch package information from AUR RPC.") from e

    def _choose_provider(self, dep: str, possible_providers: list[str],
                         where: str) -> typing.Optional[PackageInfo]:
        min_selection = 1
        max_selection = len(possible_providers)
        l.print_summary(
            f"Found {len(possible_providers)} providers for {dep} from {where}."
        )

        providers = "Providers: "
        for index, name in enumerate(possible_providers):
            providers += f"{index + 1}:{name} "
        l.print_info(providers)

        selection = l.prompt_number(
            f"Select a provider [{min_selection}-{max_selection}] (default: {min_selection}): ",
            min_selection,
            max_selection,
            default=min_selection)

        info = self.get_package_info(possible_providers[selection - 1])
        if info is not None:
            self._dep_provider_cache[dep] = info
        return info


class ResolvedDependencies:
    """
    Result of dependency resolution.
    """

    def __init__(self):
        self.pacman_deps: set[str] = set()
        self.foreign_pkgs: set[str] = set()
        self.foreign_dep_pkgs: set[str] = set()
        self.foreign_build_dep_pkgs: set[str] = set()
        self.build_order: list[str] = []
        self.packages: dict[str, ForeignPackage] = {}
        self._pkgbases_to_pkgs: dict[str, set[str]] = {}
        self._pkgs_to_pkgbases: dict[str, str] = {}

    def add_pkgbase_info(self, pkgname: str, pkgbase: str):
        """
        Adds information about a which package belongs in which package base.
        """
        pkgs = self._pkgbases_to_pkgs.get(pkgbase, set())
        pkgs.add(pkgname)
        self._pkgbases_to_pkgs[pkgbase] = pkgs
        self._pkgs_to_pkgbases[pkgname] = pkgbase

    def get_pkgbase(self, pkgname: str) -> str:
        """
        Returns the package base of an package.
        """
        return self._pkgs_to_pkgbases[pkgname]

    def get_pkgs_with_common_pkgbase(self, pkgname: str) -> set[str]:
        """
        Returns all packages that have the same package base as the given package.
        """
        pkgbase = self._pkgs_to_pkgbases[pkgname]
        return self._pkgbases_to_pkgs[pkgbase]

    def all_pkgbases(self) -> list[str]:
        """
        Returns all pkgbases.
        """
        return list(self._pkgbases_to_pkgs)

    def get_some_pkgname(self, pkgbase: str) -> str:
        """
        Returns some package name that the given pkgbase has.
        """
        return list(self._pkgbases_to_pkgs[pkgbase])[0]


class ForeignPackageManager:
    """
    Class for dealing with AUR/user packages.
    """

    def __init__(self, store: l.Store, pacman: l.Pacman,
                 search: ExtendedPackageSearch):
        self._store = store
        self._pacman = pacman
        self._search = search

    def upgrade(self, upgrade_devel: bool = False):
        """
        Upgrades all AUR/user packages.
        """
        all_foreign_pkgs = self._pacman.get_versioned_foreign_packages()
        all_explicit_pkgs = set(self._pacman.get_installed())
        l.print_debug(
            f"Foreign packages to check for upgrades: {all_foreign_pkgs}")

        to_upgrade = []
        as_explicit = []
        for pkg, ver in all_foreign_pkgs:
            info = self._search.get_package_info(pkg)
            if info is None:
                raise l.UserFacingError(f"Failed to find package: {pkg}.")

            if self.should_upgrade_package(pkg, ver, info.version,
                                           upgrade_devel):
                to_upgrade.append(pkg)
            if pkg in all_explicit_pkgs:
                as_explicit.append(pkg)

        l.print_debug(
            f"The following foreign packages will be upgraded: {' '.join(to_upgrade)}"
        )

        self.install(to_upgrade, as_explicit, True)

    def install(self,
                foreign_pkgs: list[str],
                as_explicit: typing.Optional[list[str]] = None,
                force: bool = False):
        """
        Installs the given AUR/user packages and their dependencies (both pacman/AUR).
        """

        if len(foreign_pkgs) == 0:
            return

        resolved_dependencies = self.resolve_dependencies(foreign_pkgs)

        l.print_summary(
            "The following foreign packages will be installed explicitly:")
        l.print_continuation("")
        l.print_continuation(
            f"\t{' '.join(resolved_dependencies.foreign_pkgs)}")
        l.print_continuation("")

        if resolved_dependencies.foreign_dep_pkgs:
            l.print_summary(
                "The following foreign packages will be installed as dependencies:"
            )
            l.print_continuation("")
            l.print_continuation(
                f"\t{' '.join(resolved_dependencies.foreign_dep_pkgs)}")
            l.print_continuation("")

        if resolved_dependencies.foreign_build_dep_pkgs:
            l.print_summary(
                "The following foreign packages will be built in order to install other packages. They will not be installed:"
            )
            l.print_continuation("")
            l.print_continuation(
                f"\t{' '.join(resolved_dependencies.foreign_build_dep_pkgs)}")
            l.print_continuation("")

        if not l.prompt_confirm("Proceed?", default=True):
            raise l.UserFacingError("Installing aborted.")

        l.print_summary(
            "Installing AUR/user package dependencies from pacman.")
        self._pacman.install_dependencies(
            list(resolved_dependencies.pacman_deps))

        try:
            with PackageBuilder(self._search, self._store,
                                resolved_dependencies) as builder:
                while resolved_dependencies.build_order:
                    to_build = resolved_dependencies.build_order.pop(0)

                    pkgbase = resolved_dependencies.get_pkgbase(to_build)
                    package_names = resolved_dependencies.get_pkgs_with_common_pkgbase(
                        to_build)

                    packages = [
                        resolved_dependencies.packages[pkgname]
                        for pkgname in package_names
                    ]

                    builder.build_packages(pkgbase, packages, force)
        except (subprocess.CalledProcessError, OSError) as e:
            raise l.UserFacingError("Failed to build packages.") from e

        if as_explicit is None:
            as_explicit = list(resolved_dependencies.foreign_pkgs)

        packages_to_install = list(resolved_dependencies.foreign_pkgs)
        packages_to_install += list(resolved_dependencies.foreign_dep_pkgs)

        package_files_to_install = []
        for pkg in packages_to_install:
            built_pkg = self._store.get_package(pkg)
            assert built_pkg is not None
            _, path = built_pkg
            package_files_to_install.append(path)

        if package_files_to_install or force:
            l.print_summary("Installing AUR/user packages.")
            self._pacman.install_files(package_files_to_install, as_explicit)
        else:
            l.print_summary("No packages to install.")

    def resolve_dependencies(
            self, foreign_packages: list[str]) -> ResolvedDependencies:
        """
        Resolves AUR/user dependencies of AUR/user packages.

        Returns a tuple of (foreign_packages, pacman_deps)

        foreign_packages are in the order they should be built
        (the 1st element should be built 1st)

        pacman_deps are dependencies that are required by the AUR/user packages.
        """

        l.print_summary("Resolving AUR / user package dependencies.")
        l.print_debug(f"Packages: {foreign_packages}")

        result = ResolvedDependencies()
        result.foreign_pkgs = set(foreign_packages)

        graph = DepGraph()

        for name in foreign_packages:
            graph.add_requirement(name, None)

        seen_packages = set(foreign_packages)
        to_process = list(foreign_packages)
        total_processed = 0

        def process_dep(pkgname: str, depname: str, add_to: set[str]):
            dep_info = self._search.find_provider(depname)

            if dep_info is None:
                raise l.UserFacingError(
                    f"Failed to find '{depname}' from AUR or user provided packages."
                )

            add_to.add(dep_info.pkgname)

            l.print_debug(
                f"Adding dependency {dep_info.pkgname} to package {pkgname}.")
            graph.add_requirement(dep_info.pkgname, pkgname)
            if dep_info.pkgname not in seen_packages:
                to_process.append(dep_info.pkgname)
                seen_packages.add(dep_info.pkgname)

        while to_process:
            pkgname = to_process.pop()

            info = self._search.get_package_info(pkgname)
            if info is None:
                raise l.UserFacingError(
                    f"Failed to find '{pkgname}' from AUR or user provided packages."
                )

            result.pacman_deps.update(info.pacman_dependencies)
            result.add_pkgbase_info(pkgname, info.pkgbase)

            build_deps = info.foreign_make_dependencies_stripped + info.foreign_check_dependencies_stripped

            self._search.try_caching_packages(
                info.foreign_dependencies_stripped + build_deps)

            for depname in info.foreign_dependencies_stripped:
                process_dep(pkgname, depname, result.foreign_dep_pkgs)

            for depname in build_deps:
                process_dep(pkgname, depname, result.foreign_build_dep_pkgs)

            total_processed += 1
            l.print_info(f"{total_processed}/{len(seen_packages)}.")

        l.print_summary("Determining build order.")

        while True:
            to_add = graph.get_and_remove_outer_dep_pkgs()

            if len(to_add) == 0:
                break

            for pkg in to_add:
                if pkg not in result.packages:
                    l.print_debug(f"Adding {pkg} to build_order.")
                    result.build_order.append(pkg.name)
                    result.packages[pkg.name] = pkg

        return result

    def should_upgrade_package(self,
                               package: str,
                               installed_version: str,
                               fetched_version: str,
                               upgrade_devel=False) -> bool:
        """
        Returns True if a package should be upgraded.
        """

        if upgrade_devel and is_devel(package):
            return True

        try:
            result = int(
                subprocess.run(conf.commands.compare_versions(
                    installed_version, fetched_version),
                               check=True,
                               stdout=subprocess.PIPE).stdout.decode())
            return result < 0
        except (ValueError, subprocess.CalledProcessError) as error:
            raise l.UserFacingError("Failed to compare versions.") from error


class PackageBuilder:
    """
    Used for building packages in a chroot.
    """

    always_included_packages = ["base-devel", "git"]

    def __init__(self, search: ExtendedPackageSearch, store: l.Store,
                 resolved_deps: ResolvedDependencies):
        self._search = search
        self._store = store
        self._resolved_deps = resolved_deps
        self.chroot_wd_dir = os.path.join(conf.build_dir, "chroot")
        self.chroot_dir = os.path.join(self.chroot_wd_dir, "root")
        self.pkgbase_dir_map = {}
        self.original_wd = ""

    def __enter__(self):
        self.store_wd()
        self.create_build_environment()

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.restore_wd()
        self.remove_build_environment()

    def store_wd(self):
        """
        Remembers the current working directory as the original working directory.
        """
        self.original_wd = os.getcwd()

    def restore_wd(self):
        """
        Returns to the original working directory.
        """
        os.chdir(self.original_wd)

    def create_build_environment(self):
        """
        Creates a new chroot and clones all PKGBUILDS.
        """
        l.print_summary("Creating a build environment..")

        if os.path.exists(conf.build_dir):
            l.print_info("Removing previous build directory.")
            self.remove_build_environment()

        l.print_info("Getting all PKGBUILDS.")

        # Set up PKGBUILDS
        for pkgbase in self._resolved_deps.all_pkgbases():
            pkgbuild_dir = os.path.join(conf.build_dir, pkgbase)
            self.pkgbase_dir_map[pkgbase] = pkgbuild_dir
            os.makedirs(pkgbuild_dir)
            os.chdir(pkgbuild_dir)

            git_url = self._search.get_package_info(
                self._resolved_deps.get_some_pkgname(pkgbase)
            ).git_url  # pyright: ignore[reportOptionalMemberAccess]

            l.print_debug(f"Git URL for '{pkgbase}' is '{git_url}'")
            self._git_clone_and_review_pkgbuild(pkgbase, git_url)
            shutil.chown(pkgbuild_dir, user=conf.makepkg_user)

        l.print_summary("Creating a new chroot.")
        os.makedirs(self.chroot_wd_dir)

        # Remove GNUPGHOME from mkarchroot environment variables since it may interfere with
        # the chroot creation
        mkarchroot_env_vars = os.environ.copy()
        try:
            del mkarchroot_env_vars["GNUPGHOME"]
            l.print_debug(
                "Removed GNUPGHOME variable from mkarchroot environment.")
        except KeyError:
            pass

        subprocess.run(conf.commands.make_chroot(
            self.chroot_dir, PackageBuilder.always_included_packages +
            list(self._resolved_deps.pacman_deps)),
                       env=mkarchroot_env_vars,
                       check=True,
                       capture_output=conf.quiet_output)

    def remove_build_environment(self):
        """
        Deletes the build environment.
        """
        shutil.rmtree(conf.build_dir)

    def build_packages(self, package_base: str, packages: list[ForeignPackage],
                       force: bool):
        """
        Builds package(s) with the same package base.

        Set force to true to force rebuilds of packages that are already cached
        """

        package_names = list(map(lambda p: p.name, packages))

        # Rebuild is only needed if at least one package is not in the cache.

        if self._are_all_pkgs_cached(packages) and not force:
            l.print_summary(
                f"Skipped building '{' '.join(package_names)}'. Already up to date."
            )
            return

        l.print_summary(f"To build '{' '.join(package_names)}'.")

        chroot_new_pacman_pkgs, chroot_pkg_files = self._get_chroot_packages(
            packages)

        pkgbuild_dir = self.pkgbase_dir_map[package_base]
        os.chdir(pkgbuild_dir)

        l.print_debug(
            f"Chroot dir is: '{self.chroot_dir}', pkgbuild dir is '{pkgbuild_dir}'."
        )

        l.print_info("Installing build dependencies to chroot.")

        subprocess.run(conf.commands.install_chroot_packages(
            self.chroot_dir,
            chroot_new_pacman_pkgs + PackageBuilder.always_included_packages),
                       check=True,
                       capture_output=conf.quiet_output)

        l.print_info("Making package.")

        subprocess.run(conf.commands.make_chroot_pkg(self.chroot_wd_dir,
                                                     conf.makepkg_user,
                                                     chroot_pkg_files),
                       check=True,
                       capture_output=conf.quiet_output)

        for pkgname in package_names:
            file = self._find_pkgfile(pkgname, pkgbuild_dir)

            dest = shutil.copy(file, conf.pkg_cache_dir)

            version = self._search.get_package_info(
                pkgname).version  # pyright: ignore[reportOptionalMemberAccess]

            l.print_debug(
                f"Adding '{pkgname}', version: '{version}' to cache as file '{dest}'."
            )

            self._store.add_package_to_cache(pkgname, version, dest)

        l.print_info("Removing build dependencies from chroot.")

        subprocess.run(conf.commands.remove_chroot_packages(
            self.chroot_dir, chroot_new_pacman_pkgs),
                       check=True,
                       capture_output=conf.quiet_output)

        l.print_summary(f"Finished building: '{' '.join(package_names)}'.")

    def _are_all_pkgs_cached(self, pkgs: list[ForeignPackage]) -> bool:
        for pkg in pkgs:
            cache_entry = self._store.get_package(pkg.name)
            if cache_entry is None:
                return False
            cached_version, _ = cache_entry
            # resolve_dependencies gets info for every package so info cannot be None
            fetched_version = self._search.get_package_info(
                pkg.name
            ).version  # pyright: ignore[reportOptionalMemberAccess]

            if cached_version != fetched_version or is_devel(pkg.name):
                return False
        return True

    def _get_chroot_packages(
            self, pkgs_to_build: list[ForeignPackage]
    ) -> tuple[list[str], list[str]]:
        """
        Returns a tuple of pacman build dependencies and built foreign pkgs files that are needed
        in the chroot before building. pkgs_to_build share the same pkgbase.
        """
        chroot_pacman_build_deps = set()
        chroot_foreign_pkgs = set()

        def add_to_pacman_build_deps(deps: list[str]):
            for dep in deps:
                if dep not in self._resolved_deps.pacman_deps:
                    chroot_pacman_build_deps.add(dep)

        for pkg in pkgs_to_build:
            info = self._search.get_package_info(pkg.name)
            assert info is not None

            add_to_pacman_build_deps(info.pacman_make_dependencies)
            add_to_pacman_build_deps(info.pacman_check_dependencies)

            foreign_deps = pkg.get_all_recursive_foreign_deps()
            chroot_foreign_pkgs.update(foreign_deps)

            # Add pacman deps of foreign packages
            for dep in foreign_deps:
                dep_info = self._search.get_package_info(dep)
                assert dep_info is not None

                add_to_pacman_build_deps(dep_info.pacman_make_dependencies)
                add_to_pacman_build_deps(dep_info.pacman_check_dependencies)

        # Packages with the same pkgbase might depend on each other,
        # but they don't need to be installed for the build to succeed.
        for pkg in pkgs_to_build:
            if pkg.name in chroot_foreign_pkgs:
                chroot_foreign_pkgs.remove(pkg.name)

        chroot_foreign_pkg_files = []

        for foreign_pkg in chroot_foreign_pkgs:
            entry = self._store.get_package(foreign_pkg)
            assert entry is not None, "Build order determines that the dependencies are built \
                    before and thus are found in the cache."

            _, file = entry

            chroot_foreign_pkg_files.append(file)

        return (list(chroot_pacman_build_deps), chroot_foreign_pkg_files)

    def _find_pkgfile(self, pkgname: str, pkgbuild_dir: str) -> str:
        # HACK: Because we don't know the pkgarch we can't be sure what is the build result.
        # Instead: we just try with pre- and postfixes.

        matches = []

        info = self._search.get_package_info(pkgname)
        assert info is not None
        prefix = info.pkg_file_prefix()

        for file in os.scandir(pkgbuild_dir):
            if file.is_file() and file.name.startswith(prefix):
                for ext in conf.valid_pkgexts:
                    if file.name.endswith(ext):
                        matches.append(file.path)
                        continue

        if len(matches) != 1:
            raise l.UserFacingError(
                f"Failed to build package '{pkgname}', because the pkg file cannot be determined."
            )

        return matches[0]

    def _git_clone_and_review_pkgbuild(self, pkgbase: str, git_url: str):
        """
        Clones an PKGBUILD to the current directory.

        The user is prompted to review the PKGBUILD and confirm if the package should be built.
        """
        try:
            subprocess.run(conf.commands.git_clone(git_url, "."),
                           check=True,
                           capture_output=conf.quiet_output)

            if l.prompt_confirm(f"Review PKGBUILD for {pkgbase}?",
                                default=True):
                latest_reviewed_commit = self._store.pkgbuild_latest_reviewed_commits.get(
                    pkgbase)
                if latest_reviewed_commit is None:
                    for file in os.scandir("."):
                        if file.is_file() and not file.name.startswith("."):
                            subprocess.run(conf.commands.review_file(
                                file.path),
                                           check=True)
                else:
                    subprocess.run(
                        conf.commands.git_diff(latest_reviewed_commit),
                        check=True)

            if l.prompt_confirm("Build this package?", default=True):
                commit_id = subprocess.run(
                    conf.commands.git_get_commit_id(),
                    check=True,
                    capture_output=True).stdout.decode().strip()
                self._store.pkgbuild_latest_reviewed_commits[
                    pkgbase] = commit_id
            else:
                raise l.UserFacingError("Building aborted.")

        except subprocess.CalledProcessError as error:
            raise l.UserFacingError(
                f"Failed to clone and review PKGBUILD from {git_url}"
            ) from error
