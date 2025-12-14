import dataclasses
import os
import pathlib
import re
import tempfile

import requests  # type: ignore

import decman.config as config
import decman.core.command as command
import decman.core.error as errors
import decman.core.output as output
from decman.plugins.aur.commands import AurCommands, AurPacmanInterface
from decman.plugins.aur.error import AurRPCError, PKGBUILDParseError


def strip_dependency(dep: str) -> str:
    """
    Removes version spefications from a dependency name.
    """
    rx = re.compile("(=.*|>.*|<.*)")
    return rx.sub("", dep)


@dataclasses.dataclass(frozen=True, slots=True)
class PackageInfo:
    """
    Immutable description of a package to be built or installed.

    This class represents *resolved* package metadata and is intended to be
    passed around as pure data.

    Exactly one source must be specified:
    - ``git_url`` for VCS-based (e.g. AUR) packages
    - ``pkgbuild_directory`` for local PKGBUILD-based packages

    Invariants:
    - ``pkgname`` uniquely identifies the package.
    - ``pkgbase`` groups split packages.
    - Exactly one of ``git_url`` or ``pkgbuild_directory`` is set.
    - All dependency containers are immutable.

    This object is safe for hashing, set membership, and reuse across runs.
    """

    pkgname: str
    pkgbase: str
    version: str

    git_url: str | None = None
    pkgbuild_directory: str | None = None
    provides: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    dependencies: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    make_dependencies: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    check_dependencies: tuple[str, ...] = dataclasses.field(default_factory=tuple)

    # Caches (excluded from eq/hash)
    _native_dependencies: tuple[str, ...] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )
    _foreign_dependencies: tuple[str, ...] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )

    _native_make_dependencies: tuple[str, ...] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )
    _foreign_make_dependencies: tuple[str, ...] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )

    _native_check_dependencies: tuple[str, ...] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )
    _foreign_check_dependencies: tuple[str, ...] | None = dataclasses.field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.git_url is None and self.pkgbuild_directory is None:
            raise ValueError("Both git_url and pkgbuild_directory cannot be None.")

        if self.git_url is not None and self.pkgbuild_directory is not None:
            raise ValueError("Both git_url and pkgbuild_directory cannot be set.")

    def pkg_file_prefix(self) -> str:
        """
        Returns the beginning of the file created from building this package.
        """
        return f"{self.pkgname}-{self.version}"

    # --- public API ---------------------------------------------------------

    def foreign_dependencies(self, pacman: AurPacmanInterface) -> list[str]:
        """
        Returns a list of foreign dependencies of this package.

        The dependencies are stripped of their version constraints if there are any.
        """
        self._ensure_dependencies_cached(pacman)
        assert self._foreign_dependencies is not None
        return list(self._foreign_dependencies)

    def foreign_make_dependencies(self, pacman: AurPacmanInterface) -> list[str]:
        """
        Returns a list of foreign make dependencies of this package.

        The dependencies are stripped of their version constraints if there are any.
        """
        self._ensure_make_dependencies_cached(pacman)
        assert self._foreign_make_dependencies is not None
        return list(self._foreign_make_dependencies)

    def foreign_check_dependencies(self, pacman: AurPacmanInterface) -> list[str]:
        """
        Returns a list of foreign check dependencies of this package.

        The dependencies are stripped of their version constraints if there are any.
        """
        self._ensure_check_dependencies_cached(pacman)
        assert self._foreign_check_dependencies is not None
        return list(self._foreign_check_dependencies)

    def native_dependencies(self, pacman: AurPacmanInterface) -> list[str]:
        """
        Returns a list of native dependencies of this package.

        The dependencies are stripped of their version constraints if there are any.
        """
        self._ensure_dependencies_cached(pacman)
        assert self._native_dependencies is not None
        return list(self._native_dependencies)

    def native_make_dependencies(self, pacman: AurPacmanInterface) -> list[str]:
        """
        Returns a list of native make dependencies of this package.

        The dependencies are stripped of their version constraints if there are any.
        """
        self._ensure_make_dependencies_cached(pacman)
        assert self._native_make_dependencies is not None
        return list(self._native_make_dependencies)

    def native_check_dependencies(self, pacman: AurPacmanInterface) -> list[str]:
        """
        Returns a list of native check dependencies of this package.

        The dependencies are stripped of their version constraints if there are any.
        """
        self._ensure_check_dependencies_cached(pacman)
        assert self._native_check_dependencies is not None
        return list(self._native_check_dependencies)

    # --- internal helpers ---------------------------------------------------

    @staticmethod
    def _classify_dependencies(
        deps: tuple[str, ...], pacman: AurPacmanInterface
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        native: list[str] = []
        foreign: list[str] = []

        for dependency in deps:
            stripped = strip_dependency(dependency)
            if pacman.is_installable(dependency):
                native.append(stripped)
            else:
                foreign.append(stripped)

        return tuple(native), tuple(foreign)

    def _ensure_dependencies_cached(self, pacman: AurPacmanInterface) -> None:
        if self._native_dependencies is not None:
            return

        native, foreign = self._classify_dependencies(self.dependencies, pacman)
        object.__setattr__(self, "_native_dependencies", native)
        object.__setattr__(self, "_foreign_dependencies", foreign)

    def _ensure_make_dependencies_cached(self, pacman: AurPacmanInterface) -> None:
        if self._native_make_dependencies is not None:
            return

        native, foreign = self._classify_dependencies(self.make_dependencies, pacman)
        object.__setattr__(self, "_native_make_dependencies", native)
        object.__setattr__(self, "_foreign_make_dependencies", foreign)

    def _ensure_check_dependencies_cached(self, pacman: AurPacmanInterface) -> None:
        if self._native_check_dependencies is not None:
            return

        native, foreign = self._classify_dependencies(self.check_dependencies, pacman)
        object.__setattr__(self, "_native_check_dependencies", native)
        object.__setattr__(self, "_foreign_check_dependencies", foreign)


class CustomPackage:
    """
    Custom package installed from some other location than the official repos or the AUR.

    ``pkgname`` is required because the PKGBUILD might be for split packages.

    Exactly one of ``git_url`` or ``pkgbuild_directory`` must be provided.

    Parameters:
        ``pkgname``:
            Name of the package.

        ``git_url``:
            URL to a git repository containing the PKGBUILD.

        ``pkgbuild_directory``:
            Path to the directory containing the PKGBUILD.
    """

    def __init__(self, pkgname: str, git_url: str | None, pkgbuild_directory: str | None) -> None:
        if git_url is None and pkgbuild_directory is None:
            raise ValueError("Both git_url and pkgbuild_directory cannot be None.")

        if git_url is not None and pkgbuild_directory is not None:
            raise ValueError("Both git_url and pkgbuild_directory cannot be set.")

        self.pkgname = pkgname
        self.git_url = git_url
        self.pkgbuild_directory = pkgbuild_directory

    def parse(self, commands: AurCommands) -> PackageInfo:
        """
        Parses this package's PKGBUILD to ``PackageInfo``.

        If this fails, raises a ``PKGBUILDParseError``.
        """
        if self.pkgbuild_directory is not None:
            srcinfo = self._srcinfo_from_pkgbuild_directory(commands)
        else:
            srcinfo = self._srcinfo_from_git(commands)

        return self._parse_srcinfo(srcinfo)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CustomPackage):
            return False
        return (
            self.git_url == other.git_url
            and self.pkgbuild_directory == other.pkgbuild_directory
            and self.pkgname == other.pkgname
        )

    def __hash__(self) -> int:
        return hash((self.pkgname, self.git_url, self.pkgbuild_directory))

    def __str__(self) -> str:
        if self.git_url is not None:
            return f"CustomPackage(pkgname={self.pkgname}, git_url={self.git_url})"
        return (
            f"CustomPackage(pkgname={self.pkgname}, pkgbuild_directory={self.pkgbuild_directory})"
        )

    def _srcinfo_from_pkgbuild_directory(self, commands: AurCommands) -> str:
        assert self.pkgbuild_directory is not None, (
            "This will not get called if pkgbuild_directory is unset."
        )

        path = pathlib.Path(self.pkgbuild_directory)
        if not path.is_dir():
            raise PKGBUILDParseError(
                self.git_url,
                self.pkgbuild_directory,
                f"pkgbuild_directory '{path}' does not exist or is not a directory.",
            )

        if not (path / "PKGBUILD").exists():
            raise PKGBUILDParseError(
                self.git_url, self.pkgbuild_directory, f"No PKGBUILD found in '{path}'."
            )

        return self._run_makepkg_printsrcinfo(path, commands)

    def _srcinfo_from_git(self, commands: AurCommands) -> str:
        assert self.git_url is not None, "This will not get called if git_url is unset."
        with tempfile.TemporaryDirectory(prefix="decman-pkgbuild-") as tmpdir:
            tmp_path = pathlib.Path(tmpdir)
            try:
                cmd = commands.git_clone(self.git_url, tmpdir)
                command.check_run_result(cmd, command.run(cmd))
            except errors.CommandFailedError as error:
                raise PKGBUILDParseError(
                    self.git_url, self.pkgbuild_directory, "Failed to clone PKGBUILD repository."
                ) from error

            if not (tmp_path / "PKGBUILD").exists():
                raise PKGBUILDParseError(
                    self.git_url,
                    self.pkgbuild_directory,
                    f"Cloned repository '{self.git_url}' does not contain a PKGBUILD.",
                )

            return self._run_makepkg_printsrcinfo(tmp_path, commands)

    def _run_makepkg_printsrcinfo(self, path: pathlib.Path, commands: AurCommands) -> str:
        orig_wd = os.getcwd()
        try:
            os.chdir(path)
            cmd = commands.print_srcinfo()
            _, srcinfo = command.check_run_result(cmd, command.run(cmd))
        except errors.CommandFailedError as error:
            raise PKGBUILDParseError(
                self.git_url, self.pkgbuild_directory, "Failed to generate SRCINFO using makepkg."
            ) from error
        finally:
            os.chdir(orig_wd)

        return srcinfo

    def _parse_srcinfo(self, srcinfo: str) -> PackageInfo:
        pkgbase: str | None = None
        pkgver: str | None = None
        pkgrel: str | None = None
        epoch: str | None = None
        provides: list[str] = []

        # I'm not sure if split packages can have dependencies listed in the base.
        # Easy to handle regardless
        base_depends: list[str] = []
        base_makedepends: list[str] = []
        base_checkdepends: list[str] = []

        pkg_depends: list[str] = []
        pkg_makedepends: list[str] = []
        pkg_checkdepends: list[str] = []

        current_pkg: str | None = None
        found_pkgnames = set()

        for raw in srcinfo.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = (part.strip() for part in line.split("=", 1))

            is_base = current_pkg is None
            is_target_pkg = current_pkg == self.pkgname

            match key:
                case "pkgbase":
                    pkgbase = value
                    current_pkg = None

                case "pkgname":
                    current_pkg = value
                    found_pkgnames.add(value)

                case "pkgver":
                    if pkgver is None or current_pkg == self.pkgname:
                        pkgver = value

                case "pkgrel":
                    if pkgrel is None or current_pkg == self.pkgname:
                        pkgrel = value

                case "epoch":
                    if epoch is None or current_pkg == self.pkgname:
                        epoch = value

                case "provides":
                    if is_target_pkg:
                        provides.append(value)

                case "depends":
                    if is_base:
                        base_depends.append(value)
                    elif is_target_pkg:
                        pkg_depends.append(value)

                case "makedepends":
                    if is_base:
                        base_makedepends.append(value)
                    elif is_target_pkg:
                        pkg_makedepends.append(value)

                case "checkdepends":
                    if is_base:
                        base_checkdepends.append(value)
                    elif is_target_pkg:
                        pkg_checkdepends.append(value)

                case _ if key.startswith("depends") and key.removeprefix("depends_") == config.arch:
                    if is_base:
                        base_depends.append(value)
                    elif is_target_pkg:
                        pkg_depends.append(value)

                case _ if (
                    key.startswith("makedepends")
                    and key.removeprefix("makedepends_") == config.arch
                ):
                    if is_base:
                        base_makedepends.append(value)
                    elif is_target_pkg:
                        pkg_makedepends.append(value)

                case _ if (
                    key.startswith("checkdepends")
                    and key.removeprefix("checkdepends_") == config.arch
                ):
                    if is_base:
                        base_checkdepends.append(value)
                    elif is_target_pkg:
                        pkg_checkdepends.append(value)

        if pkgbase is None or pkgver is None:
            raise PKGBUILDParseError(
                self.git_url,
                self.pkgbuild_directory,
                "Missing required fields (pkgbase/pkgver) in SRCINFO.",
            )

        if self.pkgname not in found_pkgnames:
            raise PKGBUILDParseError(
                self.git_url,
                self.pkgbuild_directory,
                f"Package {self.pkgname} not found in SRCINFO.\
                Packages present: {' '.join(found_pkgnames)}.",
            )

        version_core = pkgver
        if pkgrel is not None:
            version_core = f"{version_core}-{pkgrel}"

        if epoch is not None:
            version = f"{epoch}:{version_core}"
        else:
            version = version_core

        return PackageInfo(
            pkgname=self.pkgname,
            pkgbase=pkgbase,
            version=version,
            git_url=self.git_url,
            pkgbuild_directory=self.pkgbuild_directory,
            provides=tuple(provides),
            dependencies=tuple(base_depends + pkg_depends),
            make_dependencies=tuple(base_makedepends + pkg_makedepends),
            check_dependencies=tuple(base_checkdepends + pkg_checkdepends),
        )


class PackageSearch:
    """
    Allows searcing for packages / providers from the AUR as well as user defined sources.

    Results are cached and custom packages are preferred.
    """

    def __init__(self, aur_rpc_timeout: int = 30) -> None:
        self._package_cache: dict[str, PackageInfo] = {}
        self._selected_providers_cache: dict[str, PackageInfo] = {}
        self._all_providers_cache: dict[str, list[str]] = {}
        self._custom_packages: list[PackageInfo] = []
        self._timeout = aur_rpc_timeout

    def add_custom_pkg(self, user_pkg: PackageInfo):
        """
        Adds the given package to custom packages.
        """
        self._custom_packages.append(user_pkg)
        self._cache_pkg(user_pkg)

    def _cache_pkg(self, pkg: PackageInfo):
        for provided_pkg in pkg.provides:
            self._all_providers_cache.setdefault(provided_pkg, []).append(pkg.pkgname)

        self._package_cache[pkg.pkgname] = pkg

    def try_caching_packages(self, packages: list[str]):
        """
        Tries caching the given packages. Virtual packages may not be cached.

        This can be used before calling get_package_info or find_provider multiple individual
        times, because then those methods don't have to make new AUR RPC requests.
        """

        uncached_packages = list(filter(lambda p: p not in self._package_cache, packages))

        if len(uncached_packages) == 0:
            return

        output.print_debug(f"Trying to cache {uncached_packages}.")

        max_pkgs_per_request = 200

        while uncached_packages:
            to_request = map(lambda p: f"arg[]={p}", uncached_packages[:max_pkgs_per_request])
            uncached_packages = uncached_packages[max_pkgs_per_request:]

            url = f"https://aur.archlinux.org/rpc/v5/info?{'&'.join(to_request)}"
            output.print_debug(f"Request URL = {url}")

            try:
                request = requests.get(url, timeout=self._timeout)
                d = request.json()

                if d["type"] == "error":
                    raise AurRPCError(f"AUR RPC returned error: {d['error']}", url)

                for result in d["results"]:
                    pkgname = result["Name"]

                    if pkgname in self._package_cache:
                        continue

                    for user_package in self._custom_packages:
                        if user_package.pkgname == pkgname:
                            output.print_debug(f"'{pkgname}' found in custom packages.")
                            self._cache_pkg(user_package)
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
                            git_url=f"https://aur.archlinux.org/{result['PackageBase']}.git",
                        )
                        self._cache_pkg(info)

                output.print_debug("Request completed.")
            except (requests.RequestException, KeyError) as e:
                raise AurRPCError(
                    f"Failed to fetch package information for {uncached_packages} from AUR RPC.",
                    url,
                ) from e

    def get_package_info(self, package: str) -> PackageInfo | None:
        """
        Returns information about a package.

        If the package is not custom, fetches information from the AUR.
        Returns None if no such AUR package exists.
        """
        output.print_debug(f"Getting info for package '{package}'.")

        if package in self._package_cache:
            output.print_debug(f"'{package}' found in cache.")
            return self._package_cache[package]

        # This code is probably not needed since all user packages should be cached
        for user_package in self._custom_packages:
            if user_package.pkgname == package:
                output.print_debug(f"'{package}' found in custom packages.")
                self._cache_pkg(user_package)
                return user_package

        url = f"https://aur.archlinux.org/rpc/v5/info/{package}"
        output.print_debug(f"Requesting info for '{package}' from AUR. URL = {url}")
        try:
            request = requests.get(url, timeout=self._timeout)
            d = request.json()

            if d["type"] == "error":
                raise AurRPCError(f"AUR RPC returned error: {d['error']}", url)

            if d["resultcount"] == 0:
                output.print_debug(f"'{package}' not found.")
                return None

            output.print_debug(f"'{package}' found from AUR.")

            result = d["results"][0]
            info = PackageInfo(
                pkgname=result["Name"],
                pkgbase=result["PackageBase"],
                version=result["Version"],
                dependencies=result.get("Depends", []),
                make_dependencies=result.get("MakeDepends", []),
                check_dependencies=result.get("CheckDepends", []),
                provides=result.get("Provides", []),
                git_url=f"https://aur.archlinux.org/{result['PackageBase']}.git",
            )

            self._cache_pkg(info)

            return info
        except (requests.RequestException, KeyError) as e:
            raise AurRPCError(
                f"Failed to fetch package information for {package} from AUR RPC.",
                url,
            ) from e

    def find_provider(self, stripped_dependency: str) -> PackageInfo | None:
        """
        Finds a provider for a dependency. The dependency should not contain version constraints.

        May prompt the user to select if multiple are available.
        """
        output.print_debug(f"Finding provider for '{stripped_dependency}'.")

        if stripped_dependency in self._selected_providers_cache:
            output.print_debug(f"'{stripped_dependency}' found in cache.")
            return self._selected_providers_cache[stripped_dependency]

        output.print_debug("Are there exact name matches?")

        exact_name_match = self.get_package_info(stripped_dependency)

        if exact_name_match is not None:
            output.print_debug("Exact name match found.")
            self._selected_providers_cache[stripped_dependency] = exact_name_match
            return exact_name_match

        output.print_debug("No exact name matches found. Finding providers.")

        known_pkg_results = self._all_providers_cache.get(stripped_dependency, [])
        for user_package in self._custom_packages:
            if (
                stripped_dependency in user_package.provides
                and stripped_dependency not in known_pkg_results
            ):
                known_pkg_results.append(user_package.pkgname)

        if len(known_pkg_results) == 1:
            pkg = self.get_package_info(known_pkg_results[0])
            assert pkg is not None
            output.print_debug(
                f"Single provider for '{stripped_dependency}' found in known packages: '{pkg}'."
            )
            self._selected_providers_cache[stripped_dependency] = pkg
            return pkg

        if len(known_pkg_results) > 1:
            return self._choose_provider(stripped_dependency, known_pkg_results, "user packages")

        url = f"https://aur.archlinux.org/rpc/v5/search/{stripped_dependency}?by=provides"
        output.print_debug(
            f"Requesting providers for '{stripped_dependency}' from AUR. URL = {url}"
        )
        try:
            request = requests.get(url, timeout=self._timeout)
            d = request.json()

            if d["type"] == "error":
                raise AurRPCError(f"AUR RPC returned error: {d['error']}", url)

            if d["resultcount"] == 0:
                output.print_debug(f"'{stripped_dependency}' not found.")
                return None

            results = list(map(lambda r: r["Name"], d["results"]))

            if len(results) == 1:
                pkgname = results[0]
                output.print_debug(
                    f"Single provider for '{stripped_dependency}' found from AUR: '{pkgname}'"
                )
                info = self.get_package_info(pkgname)
                return info

            return self._choose_provider(stripped_dependency, results, "AUR")
        except (requests.RequestException, KeyError) as e:
            raise AurRPCError(
                f"Failed to search for {stripped_dependency} from AUR RPC.",
                url,
            ) from e

    def _choose_provider(
        self, dep: str, possible_providers: list[str], where: str
    ) -> PackageInfo | None:
        min_selection = 1
        max_selection = len(possible_providers)
        output.print_summary(f"Found {len(possible_providers)} providers for {dep} from {where}.")

        providers = "Providers: "
        for index, name in enumerate(possible_providers):
            providers += f"{index + 1}:{name} "
        output.print_summary(providers)

        selection = output.prompt_number(
            f"Select a provider [{min_selection}-{max_selection}] (default: {min_selection}): ",
            min_selection,
            max_selection,
            default=min_selection,
        )

        info = self.get_package_info(possible_providers[selection - 1])
        if info is not None:
            self._selected_providers_cache[dep] = info
        return info
