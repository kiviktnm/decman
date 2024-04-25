"""
Library module for decman.
"""

import pwd
import subprocess
import json
import os
import typing
import decman.config as conf
import decman

_DECMAN_MSG_TAG = "[\033[1;35mDECMAN\033[m]"
_RED_PREFIX = "\033[91m"
_YELLOW_PREFIX = "\033[93m"
_CYAN_PREFIX = "\033[96m"
_GREEN_PREFIX = "\033[92m"
_GRAY_PREFIX = "\033[90m"
_RESET_SUFFIX = "\033[m"


def print_continuation(msg: str):
    """
    Prints a message without a prefix.
    """
    print(f"{_DECMAN_MSG_TAG}\t {msg}")


def print_error(error_msg: str):
    """
    Prints an error message to the user.
    """

    print(f"{_DECMAN_MSG_TAG} {_RED_PREFIX}ERROR{_RESET_SUFFIX}: {error_msg}")


def print_warning(msg: str):
    """
    Prints a warning to the user.
    """

    print(f"{_DECMAN_MSG_TAG} {_YELLOW_PREFIX}WARNING{_RESET_SUFFIX}: {msg}")


def print_summary(msg: str):
    """
    Prints a summary message to the user.
    """

    print(f"{_DECMAN_MSG_TAG} {_CYAN_PREFIX}SUMMARY{_RESET_SUFFIX}: {msg}")


def print_info(msg: str):
    """
    Prints a detailed message to the user if verbose output is not disabled.
    """
    if conf.debug_output or not conf.quiet_output:
        print(f"{_DECMAN_MSG_TAG} INFO: {msg}")


def print_debug(msg: str):
    """
    Prints a detailed message to the user if debug messages are enabled.
    """
    if conf.debug_output:
        print(f"{_DECMAN_MSG_TAG} {_GRAY_PREFIX}DEBUG{_RESET_SUFFIX}: {msg}")


def prompt_number(msg: str,
                  min_num: int,
                  max_num: int,
                  default: typing.Optional[int] = None) -> int:
    """
    Prompts the user for a integer.
    """
    while True:
        i = input(
            f"{_DECMAN_MSG_TAG} {_GREEN_PREFIX}PROMPT{_RESET_SUFFIX}: {msg}"
        ).strip()

        if default is not None and i == "":
            return default

        try:
            num = int(i)
            if min_num <= num <= max_num:
                return num
        except ValueError:
            pass
        print_error("Invalid input.")


def prompt_confirm(msg: str, default: typing.Optional[bool] = None) -> int:
    """
    Prompts the user for confirmation.
    """

    options_suffix = "(y/n)"
    if default is not None:
        if default:
            options_suffix = "(Y/n)"
        else:
            options_suffix = "(y/N)"

    while True:
        i = input(
            f"{_DECMAN_MSG_TAG} {_GREEN_PREFIX}PROMPT{_RESET_SUFFIX} {options_suffix}: {msg} "
        ).strip()

        if default is not None and i == "":
            return default

        if i.lower() in ("y", "ye", "yes"):
            return True

        if i.lower() in ("n", "no"):
            return False

        print_error("Invalid input.")


_STORE_SAVE_DIR = "/var/lib/decman/"
_STORE_SAVE_FILENAME = "/var/lib/decman/store.json"


class Store:
    """
    Stores information between decman invocations.

    This information is used for example to prevent re-enabling a service.
    """

    def __init__(self):
        self.enabled_systemd_units: list[str] = []
        self.enabled_user_systemd_units: list[tuple[str, str]] = []
        self.enabled_modules: dict[str, str] = {}
        self.pkgbuild_latest_reviewed_commits: dict[str, str] = {}
        self._package_file_cache: dict[str, tuple[str, str]] = {}

    def get_package(self, package: str) -> typing.Optional[tuple[str, str]]:
        """
        Returns the version and the path of a package stored in the built packages cache as a tuple
        (version, path).
        """
        entry = self._package_file_cache.get(package)
        if entry is None:
            return None
        version, path = entry
        if os.path.exists(path):
            return (version, path)
        return None

    def add_package_to_cache(self, package: str, version: str,
                             path_to_built_pkg: str):
        """
        Adds a built package to the package file cache.
        """
        self._package_file_cache[package] = (version, path_to_built_pkg)

    def save(self):
        """
        Writes the store to a file.
        """

        path = os.path.join(_STORE_SAVE_DIR, _STORE_SAVE_FILENAME)

        print_debug(f"Writing Store to '{path}'.")

        d = {
            "enabled_systemd_units": self.enabled_systemd_units,
            "enabled_user_systemd_units": self.enabled_user_systemd_units,
            "enabled_modules": self.enabled_modules,
            "package_file_cache": self._package_file_cache,
            "pkgbuild_git_commits": self.pkgbuild_latest_reviewed_commits
        }

        try:
            os.makedirs(_STORE_SAVE_DIR, exist_ok=True)
            with open(path, "wt", encoding="utf-8") as file:
                json.dump(d, file)
        except OSError as e:
            raise UserFacingError("Failed to save store.") from e

    @staticmethod
    def restore() -> "Store":
        """
        Reads a saved Store from a file if it exists.
        """
        path = os.path.join(_STORE_SAVE_DIR, _STORE_SAVE_FILENAME)

        print_debug(f"Reading Store from '{path}'.")

        try:
            store = Store()

            if not os.path.exists(path):
                return store

            with open(path, "rt", encoding="utf-8") as file:
                d = json.load(file)

                store.enabled_systemd_units = d.get(
                    "enabled_systemd_units",
                    [],
                )
                store.enabled_user_systemd_units = d.get(
                    "enabled_user_systemd_units",
                    [],
                )
                store.enabled_modules = d.get("enabled_modules", {})
                store._package_file_cache = d.get("package_file_cache", {})
                store.pkgbuild_latest_reviewed_commits = d.get(
                    "pkgbuild_git_commits",
                    {},
                )

            return store
        except json.JSONDecodeError as e:
            raise UserFacingError("Failed to parse state json.") from e
        except OSError as e:
            raise UserFacingError("Failed to read saved store.") from e


class UserFacingError(Exception):
    """
    Execution of an important step failed and the program shouldn't continue.
    """

    def __init__(self, user_facing_msg: str):
        self.user_facing_msg = user_facing_msg


class Source:
    """
    Configuration that describes a system.
    """

    def __init__(
        self,
        pacman_packages: list[str],
        aur_packages: list[str],
        user_packages: list[decman.UserPackage],
        ignored_packages: list[str],
        systemd_units: list[str],
        systemd_user_units: dict[str, list[str]],
        modules: list[decman.Module],
    ):
        self.pacman_packages = pacman_packages
        self.aur_packages = aur_packages
        self.user_packages = user_packages
        self.ignored_packages = ignored_packages
        self.systemd_units = systemd_units
        self.systemd_user_units = systemd_user_units
        self.modules = modules

    def run_on_enable(self, store: Store):
        """
        Runs on_enable of every module that was now enabled.
        """
        for module in self.modules:
            if module.enabled and module.name not in store.enabled_modules:
                module.on_enable()

    def run_on_disable(self, store: Store):
        """
        Runs on_disable of every module that was now disabled.
        """
        for module in self.modules:
            if not module.enabled and module.name in store.enabled_modules:
                module.on_disable()

    def run_after_update(self):
        """
        Runs after_update of every enabled module.
        """
        for module in self.modules:
            if module.enabled:
                module.after_update()

    def run_after_version_change(self, store: Store):
        """
        Runs after_version_change of every enabled module that has it's version changed.
        """
        for module in self.modules:
            if module.enabled and module.version != store.enabled_modules.get(
                    module.name, module.version):
                module.after_version_change()
            elif module.enabled and module.name not in store.enabled_modules:
                module.after_version_change()

    def units_to_enable(self, store: Store) -> list[str]:
        """
        Returns all systemd units that should be enabled.
        """
        result = []
        for unit in self._all_units():
            if unit not in store.enabled_systemd_units:
                result.append(unit)
        return result

    def units_to_disable(self, store: Store) -> list[str]:
        """
        Returns all systemd units that should be disabled.
        """
        result = []
        for unit in store.enabled_systemd_units:
            if unit not in self._all_units():
                result.append(unit)
        return result

    def user_units_to_enable(self, store: Store) -> dict[str, list[str]]:
        """
        Returns all user systemd units that should be enabled.
        """
        result = {}
        for user, units in self._all_user_units().items():
            for unit in units:
                stored = (user, unit)
                if stored not in store.enabled_user_systemd_units:
                    entry = result.get(user, [])
                    entry.append(unit)
                    result[user] = entry
        return result

    def user_units_to_disable(self, store: Store) -> dict[str, list[str]]:
        """
        Returns all user systemd units that should be disabled.
        """
        result = {}
        for stored in store.enabled_user_systemd_units:
            user, unit = stored

            if unit not in self._all_user_units().get(user, []):
                entry = result.get(user, [])
                entry.append(unit)
                result[user] = entry
        return result

    def packages_to_remove(
            self, currently_installed_packages: list[str]) -> list[str]:
        """
        Returns all packages that should be removed. This includes pacman, aur and user packages.
        """
        result = []
        for pkg in currently_installed_packages:
            if pkg in self.ignored_packages:
                continue
            if pkg not in self._all_pkgs():
                result.append(pkg)
        return result

    def pacman_packages_to_install(
            self, currently_installed_packages: list[str]) -> list[str]:
        """
        Returns all pacman packages that should be installed.
        """
        result = []
        for pkg in self._all_pacman_pkgs():
            if pkg in self.ignored_packages:
                continue
            if pkg not in currently_installed_packages:
                result.append(pkg)
        return result

    def foreign_packages_to_install(
            self, currently_installed_packages: list[str]) -> list[str]:
        """
        Returns all aur and user packages that should be installed.
        """
        result = []
        for pkg in self._all_foreign_pkgs():
            if pkg in self.ignored_packages:
                continue
            if pkg not in currently_installed_packages:
                result.append(pkg)
        return result

    def all_enabled_modules(self) -> list[tuple[str, str]]:
        """
        Returns all enabled modules and their versions.
        """
        result = []
        for module in self.modules:
            if module.enabled:
                result.append((module.name, module.version))
        return result

    def all_user_pkgs(self) -> list[decman.UserPackage]:
        """
        Returns all active UserPackages.
        """
        result = []
        result.extend(self.user_packages)
        for module in self.modules:
            if module.enabled:
                result.extend(module.user_packages())
        return result

    def _all_pacman_pkgs(self) -> list[str]:
        result = []
        result.extend(self.pacman_packages)
        for module in self.modules:
            if module.enabled:
                result.extend(module.pacman_packages())
        return result

    def _all_foreign_pkgs(self) -> list[str]:
        result = []
        result.extend(self.aur_packages)
        result.extend(map(lambda p: p.pkgname, self.user_packages))
        for module in self.modules:
            if module.enabled:
                result.extend(module.aur_packages())
                result.extend(map(lambda p: p.pkgname, module.user_packages()))
        return result

    def _all_pkgs(self) -> list[str]:
        result = []
        result.extend(self._all_pacman_pkgs())
        result.extend(self._all_foreign_pkgs())
        return result

    def _all_units(self) -> list[str]:
        result = []
        result.extend(self.systemd_units)
        for module in self.modules:
            if module.enabled:
                result.extend(module.systemd_units())
        return result

    def _all_user_units(self) -> dict[str, list[str]]:
        result = {}
        result.update(self.systemd_user_units)
        for module in self.modules:
            if module.enabled:
                result.update(module.systemd_user_units())
        return result


class Pacman:
    """
    Interface for interacting with pacman.
    """

    def __init__(self):
        self._installable = {}

    def get_installed(self) -> list[str]:
        """
        Returns a list of installed packages.
        """

        try:
            packages = subprocess.run(
                conf.commands.list_pkgs(),
                check=True,
                stdout=subprocess.PIPE,
            ).stdout.decode().split('\n')
            return packages
        except subprocess.CalledProcessError as error:
            raise UserFacingError(
                f"Failed to get installed packages using '{error.cmd}'. Output: {error.stdout}."
            ) from error

    def is_installable(self, dep: str) -> bool:
        """
        Returns True if a dependency can be installed using pacman.
        """
        if dep in self._installable:
            return self._installable[dep]

        result = subprocess.run(conf.commands.is_installable(dep),
                                check=False,
                                capture_output=True).returncode == 0
        self._installable[dep] = result
        return result

    def get_versioned_foreign_packages(self) -> list[tuple[str, str]]:
        """
        Returns a list of installed packages and their versions that aren't from pacman databases,
        basically AUR packages.
        """
        try:
            output = subprocess.run(
                conf.commands.list_foreign_pkgs_versioned(),
                check=True,
                stdout=subprocess.PIPE).stdout.decode().strip().split('\n')
        except subprocess.CalledProcessError as error:
            raise UserFacingError(
                f"Failed to get foreign packages using '{error.cmd}'. Output: {error.stdout}."
            ) from error

        try:
            return [(line.split(" ")[0], line.split(" ")[1])
                    for line in output]
        except IndexError as error:
            raise UserFacingError(
                f"Failed to get foreign packages from pacman output. Output: {output}"
            ) from error

    def install(self, packages: list[str]):
        """
        Installs the given packages.
        """
        try:
            subprocess.run(conf.commands.install_pkgs(packages), check=True)
        except subprocess.CalledProcessError as error:
            raise UserFacingError("Failed to install packages.") from error

    def install_dependencies(self, deps: list[str]):
        """
        Installs the given dependencies.
        """
        try:
            subprocess.run(conf.commands.install_deps(deps), check=True)
        except subprocess.CalledProcessError as error:
            raise UserFacingError(
                "Failed to install dependency packages.") from error

    def install_files(self, files: list[str], as_explicit: list[str]):
        """
        Installs the given files first as dependencies. Then the packages listed in as_explicit are
        installed explicitly.
        """
        try:
            subprocess.run(conf.commands.install_files(files), check=True)
            subprocess.run(
                conf.commands.set_as_explicitly_installed(as_explicit),
                check=True,
                capture_output=conf.suppress_command_output)
        except subprocess.CalledProcessError as error:
            raise UserFacingError(
                "Failed to install foreign packages.") from error

    def upgrade(self):
        """
        Upgrades all packages.
        """
        try:
            subprocess.run(conf.commands.upgrade(), check=True)
        except subprocess.CalledProcessError as error:
            raise UserFacingError("Failed to update packages.") from error

    def remove(self, packages: list[str]):
        """
        Removes the given packages.
        """
        try:
            subprocess.run(conf.commands.remove(packages), check=True)
        except subprocess.CalledProcessError as error:
            raise UserFacingError("Failed to remove packages.") from error


class Systemd:
    """
    Interface for interacting with systemd.
    """

    def __init__(self, state: Store):
        self.state = state

    def enable_units(self, units: list[str]):
        """
        Enables the given units.
        """
        self.state.enabled_systemd_units += units
        try:
            subprocess.run(conf.commands.enable_units(units), check=True)
        except subprocess.CalledProcessError as error:
            raise UserFacingError("Failed to enable systemd units.") from error

    def disable_units(self, units: list[str]):
        """
        Disables the given units.
        """
        for unit in units:
            try:
                self.state.enabled_systemd_units.remove(unit)
            except ValueError:
                pass
        try:
            subprocess.run(conf.commands.disable_units(units), check=True)
        except subprocess.CalledProcessError as error:
            raise UserFacingError(
                "Failed to disable systemd units.") from error

    def enable_user_units(self, units: list[str], user: str):
        """
        Enables the given units for the given user.
        """
        for unit in units:
            self.state.enabled_user_systemd_units.append((user, unit))
        try:
            uid = pwd.getpwnam(user).pw_uid
            gid = pwd.getpwnam(user).pw_gid

            with subprocess.Popen(conf.commands.enable_user_units(units),
                                  start_new_session=True,
                                  group=gid,
                                  user=uid) as process:
                if process.wait() != 0:
                    raise UserFacingError(
                        f"Failed to enable systemd units for {user}.")
        except KeyError as error:
            raise UserFacingError(
                f"Failed to enable systemd units because user '{user}' doesn't exist."
            ) from error

    def disable_user_units(self, units: list[str], user: str):
        """
        Disables the given units for the given user.
        """
        for unit in units:
            try:
                self.state.enabled_user_systemd_units.remove((user, unit))
            except ValueError:
                pass
        try:
            uid = pwd.getpwnam(user).pw_uid
            gid = pwd.getpwnam(user).pw_gid

            with subprocess.Popen(conf.commands.disable_user_units(units),
                                  start_new_session=True,
                                  group=gid,
                                  user=uid) as process:
                if process.wait() != 0:
                    raise UserFacingError(
                        f"Failed to disable systemd units for {user}.")
        except KeyError as error:
            raise UserFacingError(
                f"Failed to disable systemd units because user '{user}' doesn't exist."
            ) from error
