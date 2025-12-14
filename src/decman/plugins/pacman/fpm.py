import os
import shutil
import time
import typing

import decman.core.command as command
import decman.core.error as errors
import decman.core.output as output
import decman.core.store as _store
from decman.plugins.pacman.commands import PacmanCommands
from decman.plugins.pacman.error import ForeignPackageManagerError
from decman.plugins.pacman.package import PackageSearch, PacmanInterface
from decman.plugins.pacman.resolver import DepGraph, ForeignPackage


def find_latest_cached_package(store: _store.Store, package: str) -> tuple[str, str] | None:
    """
    Returns the latest version and path of a package stored in the built packages cache as a
    tuple (version, path).
    """
    store.ensure("package_file_cache", {})
    entries = store["package_file_cache"].get(package)

    if entries is None:
        return None

    latest_version = None
    latest_path = None
    latest_timestamp = 0

    for version, path, timestamp in entries:
        if latest_timestamp < timestamp and os.path.exists(path):
            latest_timestamp = timestamp
            latest_version = version
            latest_path = path

    output.print_debug(f"Latest file for {package} is '{latest_path}'.")

    if latest_path is None:
        return None

    assert latest_version is not None, "If latest_path is set, then latest_version is set."
    return (latest_version, latest_path)


def add_package_to_cache(store: _store.Store, package: str, version: str, path_to_built_pkg: str):
    """
    Adds a built package to the package file cache. Tries to remove excess cached packages.
    """
    store.ensure("package_file_cache", {})

    new_entry = (version, path_to_built_pkg, int(time.time()))
    entries = store["package_file_cache"].get(package, [])
    for _, already_cached_path, __ in entries:
        if already_cached_path == path_to_built_pkg:
            output.print_debug(
                f"Trying to cache {package} version {version}, but the version is already cached:\
                {already_cached_path}"
            )
            return
    entries.append(new_entry)

    store["package_file_cache"][package] = entries
    clean_package_cache(store, package)


def clean_package_cache(store: _store.Store, package: str):
    oldest_path = None
    oldest_timestamp = None
    index_of_oldest = None

    entries = store["package_file_cache"][package]
    output.print_debug(f"Package cache has {len(entries)} entries.")

    number_of_packages_stored_in_cache = 3

    if len(entries) <= number_of_packages_stored_in_cache:
        output.print_debug("Old files will not be removed.")
        return

    for index, entry in enumerate(entries):
        _, path, timestamp = entry
        if oldest_timestamp is None or oldest_timestamp > timestamp:
            oldest_timestamp = timestamp
            oldest_path = path
            index_of_oldest = index

    output.print_debug(f"Oldest cached file for {package} is '{oldest_path}'.")
    if oldest_path is None:
        return
    assert index_of_oldest is not None

    entries.pop(index_of_oldest)
    if os.path.exists(oldest_path):
        output.print_debug(f"Removing '{oldest_path}' from the package cache.")
        try:
            os.remove(oldest_path)
        except OSError as e:
            output.print_error(f"Failed to remove file '{oldest_path}' from the package cache.")
            output.print_error(f"{e.strerror or e}")
            output.print_continuation("You'll have to remove the file manually.")

    store["package_file_cache"][package] = entries


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


class ResolvedDependencies:
    """
    Result of dependency resolution.
    """

    def __init__(self) -> None:
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
    Class for dealing with foreign packages.
    """

    def __init__(
        self,
        store: _store.Store,
        pacman: PacmanInterface,
        search: PackageSearch,
        commands: PacmanCommands,
        pkg_cache_dir: str,
        build_dir: str,
        makepkg_user: str,
    ):
        self._store = store
        self._pacman = pacman
        self._search = search
        self._commands = commands
        self._pkg_cache_dir = pkg_cache_dir
        self._build_dir = build_dir
        self._makepkg_user = makepkg_user

    def upgrade(
        self,
        upgrade_devel: bool = False,
        force: bool = False,
        ignored_pkgs: typing.Optional[set[str]] = None,
    ):
        """
        Upgrades all foreign packages.
        """
        if ignored_pkgs is None:
            ignored_pkgs = set()

        output.print_summary("Determining foreign packages to upgrade.")

        all_foreign_pkgs = self._pacman.get_versioned_foreign_packages()
        all_explicit_pkgs = set(self._pacman.get_installed())
        output.print_debug(f"Foreign packages to check for upgrades: {all_foreign_pkgs}")

        self._search.try_caching_packages(list(map(lambda p: p[0], all_foreign_pkgs)))

        as_explicit = []
        as_deps = []
        for pkg, ver in all_foreign_pkgs:
            if pkg in ignored_pkgs:
                continue

            info = self._search.get_package_info(pkg)
            if info is None:
                raise ForeignPackageManagerError(
                    f"Failed to find '{pkg}' from AUR or user provided packages."
                )

            if self.should_upgrade_package(pkg, ver, info.version, upgrade_devel):
                if pkg in all_explicit_pkgs:
                    as_explicit.append(pkg)
                else:
                    as_deps.append(pkg)

        output.print_debug(
            f"The following foreign packages will be upgraded: {' '.join(as_explicit)}"
        )

        self.install(as_explicit, as_deps, force)

    def install(
        self,
        foreign_pkgs: list[str],
        foreign_dep_pkgs: typing.Optional[list[str]] = None,
        force: bool = False,
    ):
        """
        Installs the given foreign packages and their dependencies (both pacman/AUR).
        """

        if foreign_dep_pkgs is None:
            foreign_dep_pkgs = []

        if len(foreign_pkgs) == 0 and len(foreign_dep_pkgs) == 0:
            return

        resolved_dependencies = self.resolve_dependencies(foreign_pkgs, foreign_dep_pkgs)

        output.print_list(
            "The following foreign packages will be installed explicitly:",
            list(resolved_dependencies.foreign_pkgs),
            level=output.SUMMARY,
        )

        output.print_list(
            "The following foreign packages will be installed as dependencies:",
            list(resolved_dependencies.foreign_dep_pkgs),
            level=output.SUMMARY,
        )

        output.print_list(
            "The following foreign packages will be built in order to install other packages.\
            They will not be installed:",
            list(resolved_dependencies.foreign_build_dep_pkgs),
            level=output.SUMMARY,
        )

        if not output.prompt_confirm("Proceed?", default=True):
            raise ForeignPackageManagerError("Installing aborted.")

        output.print_summary("Installing foreign package dependencies from pacman.")
        self._pacman.install_dependencies(resolved_dependencies.pacman_deps)

        try:
            with PackageBuilder(
                self._search,
                self._store,
                self._pacman,
                resolved_dependencies,
                self._commands,
                self._pkg_cache_dir,
                self._build_dir,
                self._makepkg_user,
            ) as builder:
                while resolved_dependencies.build_order:
                    to_build = resolved_dependencies.build_order.pop(0)

                    pkgbase = resolved_dependencies.get_pkgbase(to_build)
                    package_names = resolved_dependencies.get_pkgs_with_common_pkgbase(to_build)

                    packages = [
                        resolved_dependencies.packages[pkgname] for pkgname in package_names
                    ]

                    builder.build_packages(pkgbase, packages, force)
        except OSError as e:
            raise ForeignPackageManagerError("Failed to build packages.") from e

        packages_to_install = resolved_dependencies.foreign_pkgs
        packages_to_install |= resolved_dependencies.foreign_dep_pkgs

        package_files_to_install = []
        for pkg in packages_to_install:
            built_pkg = find_latest_cached_package(self._store, pkg)
            assert built_pkg is not None
            _, path = built_pkg
            package_files_to_install.append(path)

        if package_files_to_install or force:
            output.print_summary("Installing foreign packages.")
            self._pacman.install_files(
                package_files_to_install,
                as_explicit=resolved_dependencies.foreign_pkgs,
            )
        else:
            output.print_summary("No packages to install.")

    def resolve_dependencies(
        self,
        foreign_pkgs: list[str],
        foreign_dep_pkgs: typing.Optional[list[str]] = None,
    ) -> ResolvedDependencies:
        """
        Resolves foreign dependencies of foreign packages.
        """

        output.print_info("Resolving foreign package dependencies.")
        output.print_debug(f"Packages: {foreign_pkgs}")

        if foreign_dep_pkgs is None:
            foreign_dep_pkgs = []

        result = ResolvedDependencies()
        result.foreign_pkgs = set(foreign_pkgs)
        result.foreign_dep_pkgs = set(foreign_dep_pkgs)

        graph = DepGraph()

        for name in foreign_pkgs + foreign_dep_pkgs:
            graph.add_requirement(name, None)

        seen_packages = set(foreign_pkgs + foreign_dep_pkgs)
        to_process = foreign_pkgs + foreign_dep_pkgs
        total_processed = 0

        self._search.try_caching_packages(to_process)

        def process_dep(pkgname: str, depname: str, add_to: set[str]):
            dep_info = self._search.find_provider(depname)

            if dep_info is None:
                raise ForeignPackageManagerError(
                    f"Failed to find '{depname}' from AUR or user provided packages."
                )

            add_to.add(dep_info.pkgname)

            output.print_debug(f"Adding dependency {dep_info.pkgname} to package {pkgname}.")
            graph.add_requirement(dep_info.pkgname, pkgname)
            if dep_info.pkgname not in seen_packages:
                to_process.append(dep_info.pkgname)
                seen_packages.add(dep_info.pkgname)

        while to_process:
            pkgname = to_process.pop()

            info = self._search.get_package_info(pkgname)
            if info is None:
                raise ForeignPackageManagerError(
                    f"Failed to find '{pkgname}' from AUR or user provided packages."
                )

            result.pacman_deps.update(info.native_dependencies(self._pacman))
            result.add_pkgbase_info(pkgname, info.pkgbase)

            build_deps = info.foreign_make_dependencies(
                self._pacman
            ) + info.foreign_check_dependencies(self._pacman)

            self._search.try_caching_packages(info.foreign_dependencies(self._pacman) + build_deps)

            for depname in info.foreign_dependencies(self._pacman):
                process_dep(pkgname, depname, result.foreign_dep_pkgs)

            for depname in build_deps:
                process_dep(pkgname, depname, result.foreign_build_dep_pkgs)

            total_processed += 1
            output.print_info(f"Progress: {total_processed}/{len(seen_packages)}.")

        output.print_info("Determining build order.")

        while True:
            to_add = graph.get_and_remove_outer_dep_pkgs()

            if len(to_add) == 0:
                break

            for pkg in to_add:
                if pkg not in result.packages:
                    output.print_debug(f"Adding {pkg} to build_order.")
                    result.build_order.append(pkg.name)
                    result.packages[pkg.name] = pkg

        return result

    def should_upgrade_package(
        self,
        package: str,
        installed_version: str,
        fetched_version: str,
        upgrade_devel=False,
    ) -> bool:
        """
        Returns True if a package should be upgraded.
        """

        if upgrade_devel and is_devel(package):
            output.print_debug(f"Package {package} is devel package. It should be upgraded.")
            return True

        try:
            cmd = self._commands.compare_versions(installed_version, fetched_version)
            returncode, vercmp_output = command.run(cmd)
            if returncode != 0:
                raise errors.CommandFailedError(cmd, vercmp_output)

            should_upgrade = int(vercmp_output) < 0

            output.print_debug(
                f"Installed version is: {installed_version}. \
                Available version is {fetched_version}. Should upgrade: {should_upgrade}"
            )
            return should_upgrade
        except (ValueError, errors.CommandFailedError) as error:
            output.print_error(f"{error}")
            raise ForeignPackageManagerError("Failed to compare versions using vercmp.") from error


class PackageBuilder:
    """
    Used for building packages in a chroot.
    """

    always_included_packages = ["base-devel", "git"]

    def __init__(
        self,
        search: PackageSearch,
        store: _store.Store,
        pacman: PacmanInterface,
        resolved_deps: ResolvedDependencies,
        commands: PacmanCommands,
        pkg_cache_dir: str,
        build_dir: str,
        makepkg_user: str,
    ):
        self._search = search
        self._store = store
        self._pacman = pacman
        self._resolved_deps = resolved_deps
        self._commands = commands
        self.pkg_cache_dir = pkg_cache_dir
        self.build_dir = build_dir
        self.makepkg_user = makepkg_user
        self.valid_pkgexts = [
            ".pkg.tar",
            ".pkg.tar.gz",
            ".pkg.tar.bz2",
            ".pkg.tar.xz",
            ".pkg.tar.zst",
            ".pkg.tar.lzo",
            ".pkg.tar.lrz",
            ".pkg.tar.lz4",
            ".pkg.tar.lz",
            ".pkg.tar.Z",
        ]
        self.chroot_wd_dir = os.path.join(build_dir, "chroot")
        self.chroot_dir = os.path.join(self.chroot_wd_dir, "root")
        self.pkgbase_dir_map: dict[str, str] = {}
        self.original_wd = ""
        self._pkgs_in_chroot = set(PackageBuilder.always_included_packages)
        self._pkgs_in_chroot.update(resolved_deps.pacman_deps)

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
        output.print_info("Creating a build environment..")

        if os.path.exists(self.build_dir):
            output.print_info("Removing previous build directory.")
            self.remove_build_environment()

        output.print_info("Getting all PKGBUILDS.")

        # Set up PKGBUILDS
        for pkgbase in self._resolved_deps.all_pkgbases():
            pkgbuild_dir = os.path.join(self.build_dir, pkgbase)
            self.pkgbase_dir_map[pkgbase] = pkgbuild_dir
            os.makedirs(pkgbuild_dir)
            os.chdir(pkgbuild_dir)

            pkgbase_info = self._search.get_package_info(
                self._resolved_deps.get_some_pkgname(pkgbase)
            )

            assert pkgbase_info is not None, (
                "All dependencies and packages should be resolved \
                during the creation of ResolvedDependencies."
            )

            output.print_debug(f"Git URL for '{pkgbase}' is '{pkgbase_info.git_url}'")
            output.print_debug(
                f"PKGBUILD directory for '{pkgbase}' is '{pkgbase_info.pkgbuild_directory}'"
            )
            self._fetch_and_review_pkgbuild(
                pkgbase, pkgbase_info.git_url, pkgbase_info.pkgbuild_directory
            )
            shutil.chown(pkgbuild_dir, user=self.makepkg_user)

        output.print_info("Creating a new chroot.")
        os.makedirs(self.chroot_wd_dir)

        # Remove GNUPGHOME from mkarchroot environment variables since it may interfere with
        # the chroot creation
        mkarchroot_env_vars = os.environ.copy()
        try:
            del mkarchroot_env_vars["GNUPGHOME"]
            output.print_debug("Removed GNUPGHOME variable from mkarchroot environment.")
        except KeyError:
            pass

        cmd = self._commands.make_chroot(self.chroot_dir, self._pkgs_in_chroot)
        command.check_run_result(
            cmd, command.run(cmd, env_overrides=mkarchroot_env_vars, pass_environment=False)
        )

    def remove_build_environment(self):
        """
        Deletes the build environment.
        """
        shutil.rmtree(self.build_dir)

    def build_packages(self, package_base: str, packages: list[ForeignPackage], force: bool):
        """
        Builds package(s) with the same package base.

        Set force to true to force rebuilds of packages that are already cached
        """

        package_names = list(map(lambda p: p.name, packages))

        # Rebuild is only needed if at least one package is not in the cache.

        if self._are_all_pkgs_cached(packages) and not force:
            output.print_info(f"Skipped building '{' '.join(package_names)}'. Already up to date.")
            return

        output.print_info(f"Building '{' '.join(package_names)}'.")

        chroot_new_pacman_pkgs, chroot_pkg_files = self._get_chroot_packages(packages)

        pkgbuild_dir = self.pkgbase_dir_map[package_base]
        os.chdir(pkgbuild_dir)

        output.print_debug(f"Chroot dir is: '{self.chroot_dir}', pkgbuild dir is '{pkgbuild_dir}'.")

        output.print_info("Installing build dependencies to chroot.")

        cmd = self._commands.install_chroot(
            self.chroot_dir, chroot_new_pacman_pkgs + PackageBuilder.always_included_packages
        )
        command.check_run_result(cmd, command.run(cmd))
        output.print_info("Making package.")

        cmd = self._commands.make_chroot_pkg(
            self.chroot_wd_dir, self.makepkg_user, chroot_pkg_files
        )
        command.check_run_result(cmd, command.run(cmd))

        for pkgname in package_names:
            file = self._find_pkgfile(pkgname, pkgbuild_dir)

            dest = shutil.copy(file, self.pkg_cache_dir)

            pkg_info = self._search.get_package_info(pkgname)

            # Because all dependencies and packages should be resolved during the creation
            # of ResolvedDependencies.
            assert pkg_info is not None
            version = pkg_info.version

            output.print_debug(
                f"Adding '{pkgname}', version: '{version}' to cache as file '{dest}'."
            )

            add_package_to_cache(self._store, pkgname, version, dest)

        output.print_info("Removing build dependencies from chroot.")

        if len(chroot_new_pacman_pkgs) != 0:
            to_remove = set()
            for p in chroot_new_pacman_pkgs:
                if p not in self._pkgs_in_chroot:
                    cmd = self._commands.resolve_real_name_chroot(self.chroot_dir, p)
                    _, cmd_output = command.check_run_result(cmd, command.run(cmd))
                    real_pkgname = cmd_output.strip()
                    to_remove.add(real_pkgname)
            cmd = self._commands.remove_chroot(self.chroot_dir, to_remove)
            command.check_run_result(cmd, command.run(cmd))

        output.print_info(f"Finished building: '{' '.join(package_names)}'.")

    def _are_all_pkgs_cached(self, pkgs: list[ForeignPackage]) -> bool:
        for pkg in pkgs:
            cache_entry = find_latest_cached_package(self._store, pkg.name)
            if cache_entry is None:
                return False
            cached_version, _ = cache_entry

            pkg_info = self._search.get_package_info(pkg.name)

            # Because all dependencies and packages should be resolved during the creation
            # of ResolvedDependencies. git_url should not be None.
            assert pkg_info is not None
            fetched_version = pkg_info.version

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
            # Because all dependencies and packages should be resolved during the creation
            # of ResolvedDependencies. git_url should not be None.
            assert info is not None

            add_to_pacman_build_deps(info.native_make_dependencies(self._pacman))
            add_to_pacman_build_deps(info.native_check_dependencies(self._pacman))

            foreign_deps = pkg.get_all_recursive_foreign_dep_pkgs()
            chroot_foreign_pkgs.update(foreign_deps)

            # Add pacman deps of foreign packages
            for dep in foreign_deps:
                dep_info = self._search.get_package_info(dep)
                # Because all dependencies and packages should be resolved during the creation
                # of ResolvedDependencies. git_url should not be None.
                assert dep_info is not None

                add_to_pacman_build_deps(dep_info.native_make_dependencies(self._pacman))
                add_to_pacman_build_deps(dep_info.native_check_dependencies(self._pacman))

        # Packages with the same pkgbase might depend on each other,
        # but they don't need to be installed for the build to succeed.
        for pkg in pkgs_to_build:
            if pkg.name in chroot_foreign_pkgs:
                chroot_foreign_pkgs.remove(pkg.name)

        chroot_foreign_pkg_files = []

        for foreign_pkg in chroot_foreign_pkgs:
            entry = find_latest_cached_package(self._store, foreign_pkg)
            assert entry is not None, (
                "Build order determines that the dependencies are built \
before and thus are found in the cache."
            )

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
                for ext in self.valid_pkgexts:
                    if file.name.endswith(ext):
                        matches.append(file.path)
                        continue

        if len(matches) != 1:
            raise ForeignPackageManagerError(
                f"Failed to build package '{pkgname}', because the pkg file cannot be determined.\
                Possible files are: {matches}"
            )

        return matches[0]

    def _fetch_and_review_pkgbuild(
        self, pkgbase: str, git_url: str | None, pkgbuild_directory: str | None
    ):
        """
        Fetches a PKGBUILD to the current directory.

        PKGBUILD will be cloned using git if ``git_url`` is set.
        PKGBUILD will be copied from ``pkgbuild_directory`` if it is set.

        The user is prompted to review the PKGBUILD and confirm if the package should be built.
        """

        self._store.ensure("pkgbuild_latest_reviewed_commits", {})

        if git_url:
            cmd = self._commands.git_clone(git_url, ".")
            rc, git_output = command.run(cmd)

            if rc != 0:
                raise ForeignPackageManagerError(
                    f"Failed to clone PKGBUILD from {git_url}"
                ) from errors.CommandFailedError(cmd, git_output)

        if pkgbuild_directory:
            pkgbuild_file = os.path.join(pkgbuild_directory, "PKGBUILD")
            try:
                shutil.copy(pkgbuild_file, "./PKGBUILD")
            except OSError as error:
                raise ForeignPackageManagerError(
                    f"Failed to copy PKGBUILD from {pkgbuild_directory}."
                ) from error

        if output.prompt_confirm(f"Review PKGBUILD or show diff for {pkgbase}?", default=True):
            latest_reviewed_commit = None
            git_commit_ids = []

            if git_url:
                latest_reviewed_commit = self._store["pkgbuild_latest_reviewed_commits"].get(
                    pkgbase
                )

                cmd = self._commands.git_log_commit_ids()
                rc, git_output = command.run(cmd)

                if rc != 0:
                    raise ForeignPackageManagerError(
                        f"Failed to get git commit ids for {pkgbase}."
                    ) from errors.CommandFailedError(cmd, git_output)

                git_commit_ids = git_output.strip().split("\n")

            if latest_reviewed_commit is None or latest_reviewed_commit not in git_commit_ids:
                try:
                    for file in os.scandir("."):
                        if file.is_file() and not file.name.startswith("."):
                            cmd = self._commands.review_file(file.path)
                            rc, review_output = command.pty_run(cmd)
                            if rc != 0:
                                raise ForeignPackageManagerError(
                                    f"Failed to review file '{file.path}'."
                                ) from errors.CommandFailedError(cmd, review_output)
                except OSError as error:
                    raise ForeignPackageManagerError(
                        f"Failed to review files in directory for {pkgbase}."
                    ) from error

            else:
                cmd = self._commands.git_diff(latest_reviewed_commit)
                rc, review_output = command.pty_run(cmd)
                if rc != 0:
                    raise ForeignPackageManagerError(
                        "Failed to review file using git diff."
                    ) from errors.CommandFailedError(cmd, review_output)

        if output.prompt_confirm("Build this package?", default=True):
            cmd = self._commands.git_get_commit_id()
            rc, git_output = command.run(cmd)
            if rc != 0:
                raise ForeignPackageManagerError(
                    f"Failed to get commit id for {pkgbase}."
                ) from errors.CommandFailedError(cmd, git_output)
            commit_id = git_output.strip()
            self._store["pkgbuild_latest_reviewed_commits"][pkgbase] = commit_id
        else:
            raise ForeignPackageManagerError("Building aborted.")
