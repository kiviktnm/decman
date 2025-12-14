import dataclasses
import re

import requests  # type: ignore

import decman.core.output as output
from decman.plugins.pacman.commands import PacmanInterface
from decman.plugins.pacman.error import AurRPCError


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

    def foreign_dependencies(self, pacman: PacmanInterface) -> list[str]:
        """
        Returns a list of foreign dependencies of this package.

        The dependencies are stripped of their version constrainst if there are any.
        """
        result = []
        for dependency in self.dependencies:
            if not pacman.is_installable(dependency):
                result.append(strip_dependency(dependency))
        return result

    def foreign_make_dependencies(self, pacman: PacmanInterface) -> list[str]:
        """
        Returns a list of foreign make dependencies of this package.

        The dependencies are stripped of their version constrainst if there are any.
        """
        result = []
        for dependency in self.make_dependencies:
            if not pacman.is_installable(dependency):
                result.append(strip_dependency(dependency))
        return result

    def foreign_check_dependencies(self, pacman: PacmanInterface) -> list[str]:
        """
        Returns a list of foreign check dependencies of this package.

        The dependencies are stripped of their version constrainst if there are any.
        """
        result = []
        for dependency in self.check_dependencies:
            if not pacman.is_installable(dependency):
                result.append(strip_dependency(dependency))
        return result

    def native_dependencies(self, pacman: PacmanInterface) -> list[str]:
        """
        Returns a list of native dependencies of this package.

        The dependencies are stripped of their version constrainst if there are any.
        """
        result = []
        for dependency in self.dependencies:
            if pacman.is_installable(dependency):
                result.append(strip_dependency(dependency))
        return result

    def native_make_dependencies(self, pacman: PacmanInterface) -> list[str]:
        """
        Returns a list of native make dependencies of this package.

        The dependencies are stripped of their version constrainst if there are any.
        """
        result = []
        for dependency in self.make_dependencies:
            if pacman.is_installable(dependency):
                result.append(strip_dependency(dependency))
        return result

    def native_check_dependencies(self, pacman: PacmanInterface) -> list[str]:
        """
        Returns a list of native check dependencies of this package.

        The dependencies are stripped of their version constrainst if there are any.
        """
        result = []
        for dependency in self.check_dependencies:
            if pacman.is_installable(dependency):
                result.append(strip_dependency(dependency))
        return result


class CustomPackage:
    """
    Custom package installed from some other location than the official repos or the AUR.

    Exactly one of ``git_url`` or ``pkgbuild_directory`` must be provided.

    Parameters:
        ``git_url``:
            URL to a git repository containing the PKGBUILD.

        ``pkgbuild_directory``:
            Path to the directory containing the PKGBUILD.
    """

    def __init__(self, git_url: str | None, pkgbuild_directory: str | None) -> None:
        if git_url is None and pkgbuild_directory is None:
            raise ValueError("Both git_url and pkgbuild_directory cannot be None.")

        if git_url is not None and pkgbuild_directory is not None:
            raise ValueError("Both git_url and pkgbuild_directory cannot be set.")

        self.git_url = git_url
        self.pkgbuild_directory = pkgbuild_directory

    def parse(self) -> PackageInfo:
        """
        Parses this package's PKGBUILD to ``PackageInfo``.

        If this fails, raises a ``PKGBUILDParseError``.
        """
        raise NotImplementedError


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
