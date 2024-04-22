"""
Module for interacting with the AUR.

Optional dependencies are ignored when installing AUR packages.
Make and check dependencies are grouped together.

Terminology:

- package (pkg): name of an package from pacman repos or AUR
- dependency (dep): (virtual) package required when building and running a package
- dependency package (dep pkg): dependency that has been resolved to a package name
- build dependency: (virtual) package required when building a package (makedepends + checkdepends)
- build dependency package: build dependency that has been resolved to a package name
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


class PackageInfo:
    """
    Simplified information about an package.

    In case of AUR packages, these are fetched from AUR RPC.
    """

    def __init__(self, pkgname: str, pkgbase: str, version: str,
                 provides: list[str], dependencies: list[str],
                 make_and_check_dependencies: list[str], git_url: str):
        self.pkgname = pkgname
        self.pkgbase = pkgbase
        self.version = version
        self.dependencies = dependencies
        self.build_dependencies = make_and_check_dependencies
        self.provides = provides
        self.git_url = git_url
        self._aur_deps = None
        self._pacman_deps = None
        self._pacman_all_deps = None

    def pkg_file_prefix(self) -> str:
        """
        Returns the beginning of the file created from building this package.
        """
        return f"{self.pkgname}-{self.version}"

    def all_foreign_dependencies_stripped(self, pacman: l.Pacman) -> list[str]:
        """
        Returs a list of dependencies that cannot be installed from pacman repos.
        Includes build dependencies.

        Removes version spefications from package names.
        """
        if self._aur_deps is not None:
            return self._aur_deps

        result = []

        for p in self.dependencies:
            if not pacman.is_installable(p):
                result.append(strip_dependency(p))

        for p in self.build_dependencies:
            if not pacman.is_installable(p):
                result.append(strip_dependency(p))

        self._aur_deps = result
        return result

    def all_pacman_dependencies(self, pacman: l.Pacman) -> list[str]:
        """
        Returs a list of dependencies that can be installed from pacman repos.
        Includes build dependencies.
        """
        if self._pacman_all_deps is not None:
            return self._pacman_all_deps

        result = []

        for p in self.dependencies:
            if pacman.is_installable(p):
                result.append(strip_dependency(p))

        for p in self.build_dependencies:
            if pacman.is_installable(p):
                result.append(strip_dependency(p))

        self._pacman_all_deps = result
        return result

    def pacman_dependencies(self, pacman: l.Pacman) -> list[str]:
        """
        Returs a list of dependencies that can be installed from pacman repos.
        Doesn't include build dependencies.
        """
        if self._pacman_deps is not None:
            return self._pacman_deps

        result = []

        for p in self.dependencies:
            if pacman.is_installable(p):
                result.append(strip_dependency(p))

        self._pacman_deps = result
        return result


class ForeignPackage:
    """
    Class used to keep track of AUR/user dependency packages of an AUR/user package.
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
        return f"{self.name}: [{' '.join(self._all_recursive_foreign_deps)}]"

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
        return self._all_recursive_foreign_deps


class DepTreeNode:
    """
    Foreign package and it's dependency packages.
    """

    def __init__(self, package: str, parent: typing.Optional[typing.Self]):
        if parent is not None and package in parent.get_parent_package_names():
            raise l.UserFacingError(
                f"Foreign package dependency cycle detected involving '{package}'. \
                foreign package dependencies are also required during package building \
                and therefore dependency cycles cannot be handled.")

        self._package = ForeignPackage(package)
        self.parent = parent
        self.children: dict[str, DepTreeNode] = {}

    def get_parent_package_names(self) -> list[str]:
        """
        Returns package names of all parent nodes and self.
        """
        if self.parent is not None:
            return [self._package.name
                    ] + self.parent.get_parent_package_names()
        return [self._package.name]

    def add_dependency_package(self, pkg: str, parents: list[str]):
        """
        Adds a dependency package to this tree.

        parents is a list of names where the first element is the parent of the dependency,
        the second element is the grandparent of the dependency and so on.

        Do not include this node in the parents list.
        """
        if len(parents) == 0:
            dep = DepTreeNode(pkg, self)
            self.children[pkg] = dep
            return

        last = parents.pop()
        self.children[last].add_dependency_package(pkg, parents)

    def get_and_remove_outer_dep_pkgs(self) -> list[ForeignPackage]:
        """
        Returns all leaf nodes of the dependency package tree and removes them.
        """
        if len(self.children) == 0:
            if self.parent is not None:
                self.parent._package.add_foreign_dependency_packages(
                    [self._package.name])
                self.parent._package.add_foreign_dependency_packages(
                    self._package.get_all_recursive_foreign_deps())
                del self.parent.children[self._package.name]
            return [self._package]
        result = []
        for d in list(self.children.values()):
            result.extend(d.get_and_remove_outer_dep_pkgs())
        return result


class ExtendedPackageSearch:
    """
    Allows searcing for packages / providers from the AUR as well as user defined sources.

    Results are cached and user defined packages are preferred.
    """

    def __init__(self):
        self._package_info_cache: dict[str, PackageInfo] = {}
        self._dep_provider_cache: dict[str, PackageInfo] = {}
        self._user_packages: list[PackageInfo] = []

    def add_user_pkg(self, user_pkg: PackageInfo):
        """
        Adds the given package to user packages.
        """
        self._user_packages.append(user_pkg)

    def get_package_info(self, package: str) -> typing.Optional[PackageInfo]:
        """
        Returns information about a package.

        If the package is not user defined, fetches information from the AUR.
        Returns None if no such AUR package exists.
        """
        if package in self._package_info_cache:
            return self._package_info_cache[package]

        l.print_debug(f"Getting info for package '{package}'.")

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
                make_and_check_dependencies=result.get("MakeDepends", []) +
                result.get("CheckDepends", []),
                provides=result.get("Provides", []),
                git_url=f"https://aur.archlinux.org/{result['PackageBase']}.git"
            )

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
        if stripped_dependency in self._dep_provider_cache:
            return self._dep_provider_cache[stripped_dependency]

        l.print_debug(f"Finding provider for '{stripped_dependency}'.")
        l.print_debug("Are there exact name matches?")

        exact_name_match = self.get_package_info(stripped_dependency)

        if exact_name_match is not None:
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

        if as_explicit is None:
            as_explicit = foreign_pkgs

        all_foreign_pkgs, pacman_deps = self.resolve_dependencies(foreign_pkgs)

        l.print_summary(
            f"The following foreign packages will be installed: {' '.join(map(lambda p: p.name, all_foreign_pkgs))}"
        )

        if not l.prompt_confirm("Proceed?", default=True):
            raise l.UserFacingError("Installing aborted.")

        l.print_summary(
            "Installing AUR/user package dependencies from pacman.")
        self._pacman.install_dependencies(list(pacman_deps))

        to_install = []

        while all_foreign_pkgs:
            pkg_to_build = all_foreign_pkgs.pop(0)

            # resolve_dependencies gets info for every package so this cannot be None
            pkgbase = self._search.get_package_info(
                pkg_to_build.name
            ).pkgbase  # pyright: ignore[reportOptionalMemberAccess]
            with_same_pkgbase = []

            for other in all_foreign_pkgs:
                other_pkgbase = self._search.get_package_info(
                    other.name
                ).pkgbase  # pyright: ignore[reportOptionalMemberAccess]
                if other_pkgbase == pkgbase:
                    with_same_pkgbase.append(other)

            for other in with_same_pkgbase:
                all_foreign_pkgs.remove(other)

            to_install += self._build_pkg(pkgbase,
                                          [pkg_to_build] + with_same_pkgbase,
                                          force)

        if to_install or force:
            l.print_summary("Installing AUR/user packages.")
            self._pacman.install_files(to_install, as_explicit)
        else:
            l.print_summary("No packages to install.")

    def resolve_dependencies(
            self, foreign_packages: list[str]
    ) -> tuple[list[ForeignPackage], set[str]]:
        """
        Resolves AUR/user dependencies of AUR/user packages.

        Returns a tuple of (foreign_packages, pacman_deps)

        foreign_packages are in the order they should be built
        (the 1st element should be built 1st)

        pacman_deps are dependencies that are required by the AUR/user packages.
        """

        l.print_summary("Resolving AUR / user package dependencies.")
        l.print_debug(f"Packages: {foreign_packages}")

        # AUR packages are stored in this 2D list in the following format.
        #
        # Assume that aur_packages contains package A that should be explicitly installed.
        # A depends on B1 and B2
        # B1 depends on C
        #
        # Then the list will contain the following elements:
        # - [A]
        # - [B1,A]
        # - [B2,A]
        # - [C,B1,A]
        #
        # The list will be processed at the same time it's appended to so an actuality
        # all the elements wont be in the list at the same time
        packages_with_dependants = [[pkg] for pkg in foreign_packages]

        # Used to solve the build order of packages.
        dep_tree_root = DepTreeNode("*", None)
        pacman_deps = set()

        while packages_with_dependants:
            l.print_info(
                f"Packages remaining: {len(packages_with_dependants)}.")

            package_and_parents = packages_with_dependants.pop()

            package = package_and_parents[0]
            parents = package_and_parents[1:]

            l.print_debug(
                f"Adding package '{package}' with parents {parents} to the dependency tree."
            )
            dep_tree_root.add_dependency_package(package, parents)

            info = self._search.get_package_info(package)
            if info is None:
                raise l.UserFacingError(
                    f"Failed to find '{package}' from AUR or user provided packages."
                )

            pacman_deps.update(info.pacman_dependencies(self._pacman))

            for foreign_dep in info.all_foreign_dependencies_stripped(
                    self._pacman):
                pkg = self._search.find_provider(foreign_dep)
                if pkg is None:
                    raise l.UserFacingError(
                        f"Failed to find '{pkg}' from AUR or user provided packages."
                    )

                l.print_info("Found new package to process.")
                packages_with_dependants.append([pkg.pkgname] +
                                                package_and_parents)

        l.print_summary("Determining build order.")

        build_order = []
        while True:
            to_add = dep_tree_root.get_and_remove_outer_dep_pkgs()

            if len(to_add) == 1 and to_add[0].name == "*":
                break

            l.print_debug(f"Adding {to_add} to build_order.")

            for pkg in to_add:
                if pkg not in build_order:
                    build_order.append(pkg)

        l.print_debug(f"Build order is {build_order}")

        return (build_order, pacman_deps)

    def _build_pkg(self, package_base: str, packages: list[ForeignPackage],
                   force: bool) -> list[str]:
        """
        Builds package(s) with the same package base. Returns a list of package files to install.
        """

        package_names = list(map(lambda p: p.name, packages))

        # Rebuild is only needed if at least one package is not in the cache.

        if self._are_all_pkgs_cached(packages) and not force:
            l.print_summary(
                f"Skipped building '{' '.join(package_names)}'. Already up to date."
            )
            return []

        l.print_summary(f"To build '{' '.join(package_names)}'.")

        chroot_pacman_pkgs, chroot_pkg_files = self._get_chroot_packages(
            packages)

        chroot_dir = os.path.join(conf.build_dir, "chroot")
        pkgbuild_dir = os.path.join(conf.build_dir, "pkgbuild")

        l.print_debug(
            f"Chroot dir is: '{chroot_dir}', pkgbuild dir is '{pkgbuild_dir}'."
        )

        prev_wd = os.getcwd()

        try:
            os.makedirs(conf.pkg_cache_dir, exist_ok=True)

            if os.path.exists(conf.build_dir):
                l.print_info("Removing previous build directory.")
                shutil.rmtree(conf.build_dir)

            l.print_info("Setting up build directory.")
            os.makedirs(pkgbuild_dir)
            os.makedirs(chroot_dir)

            os.chdir(pkgbuild_dir)

            git_url = self._search.get_package_info(
                package_names[0]
            ).git_url  # pyright: ignore[reportOptionalMemberAccess]

            l.print_debug(f"Git URL for '{package_base}' is '{git_url}'")

            self.git_clone_and_review_pkgbuild(package_base, git_url)
            shutil.chown(pkgbuild_dir, user=conf.makepkg_user)

            l.print_summary(f"Building: '{' '.join(package_names)}'.")

            # Remove GNUPGHOME from mkarchroot environment variables since it may interfere with
            # the chroot creation
            mkarchroot_env_vars = os.environ.copy()
            try:
                del mkarchroot_env_vars["GNUPGHOME"]
                l.print_debug(
                    "Removed GNUPGHOME variable from mkarchroot environment.")
            except KeyError:
                pass

            l.print_info("Creating a new chroot.")

            subprocess.run(conf.commands.make_chroot(
                os.path.join(chroot_dir, "root"),
                ["base-devel"] + chroot_pacman_pkgs),
                           env=mkarchroot_env_vars,
                           check=True,
                           capture_output=conf.quiet_output)

            l.print_info("Making package.")

            subprocess.run(conf.commands.make_chroot_pkg(
                chroot_dir, conf.makepkg_user, chroot_pkg_files),
                           check=True,
                           capture_output=conf.quiet_output)

            package_files = []

            for pkgname in package_names:
                file = self._find_pkgfile(pkgname, pkgbuild_dir)

                dest = shutil.copy(file, conf.pkg_cache_dir)

                version = self._search.get_package_info(
                    pkgname
                ).version  # pyright: ignore[reportOptionalMemberAccess]

                l.print_debug(
                    f"Adding '{pkgname}', version: '{version}' to cache as file '{dest}'."
                )

                self._store.add_package_to_cache(pkgname, version, dest)
                package_files.append(dest)

            l.print_summary(f"Finished building: '{' '.join(package_names)}'.")
        except (subprocess.CalledProcessError, OSError) as error:
            raise l.UserFacingError(
                f"Failed to build package(s) '{' '.join(map(lambda p: p.name, packages))}'."
            ) from error
        finally:
            os.chdir(prev_wd)

        return package_files

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

            if cached_version != fetched_version or self.is_devel(pkg.name):
                return False
        return True

    def _get_chroot_packages(
            self, pkgs_to_build: list[ForeignPackage]
    ) -> tuple[list[str], list[str]]:
        """
        Returns a tuple of pacman packages and built foreign pkgs files that are needed in the
        chroot before building. pkgs_to_build share the same pkgbase.
        """
        chroot_pacman_pkgs = set()
        chroot_foreign_pkgs = set()

        for pkg in pkgs_to_build:
            info = self._search.get_package_info(pkg.name)
            assert info is not None

            chroot_pacman_pkgs.update(
                info.all_pacman_dependencies(self._pacman))

            foreign_deps = pkg.get_all_recursive_foreign_deps()
            chroot_foreign_pkgs.update(foreign_deps)

            # Add pacman deps of foreign packages
            for dep in foreign_deps:
                dep_info = self._search.get_package_info(dep)
                assert dep_info is not None
                chroot_pacman_pkgs.update(
                    dep_info.all_pacman_dependencies(self._pacman))

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

        return (list(chroot_pacman_pkgs), chroot_foreign_pkg_files)

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

    def git_clone_and_review_pkgbuild(self, pkgbase: str, git_url: str):
        """
        Clones an PKGBUILD to the current directory.

        The user is prompted to review the PKGBUILD and confirm if the package should be built.
        """
        try:
            subprocess.run(conf.commands.git_clone(git_url, "."), check=True)

            latest_reviewed_commit = self._store.pkgbuild_latest_reviewed_commits.get(
                pkgbase)
            if latest_reviewed_commit is None:
                for file in os.scandir("."):
                    if file.is_file() and not file.name.startswith("."):
                        subprocess.run(conf.commands.review_file(file.path),
                                       check=True)
            else:
                subprocess.run(conf.commands.git_diff(latest_reviewed_commit),
                               check=True)

            if l.prompt_confirm("Proceed with building?", default=True):
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

    def should_upgrade_package(self,
                               package: str,
                               installed_version: str,
                               fetched_version: str,
                               upgrade_devel=False) -> bool:
        """
        Returns True if a package should be upgraded.
        """

        if upgrade_devel and self.is_devel(package):
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

    def is_devel(self, package: str) -> bool:
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
