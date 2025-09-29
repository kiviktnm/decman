"""
Library module for decman.
"""

import json
import os
import pty
import shutil
import subprocess
import sys
import threading
import time
import typing

import decman
import decman.config as conf
import decman.error as err

_DECMAN_MSG_TAG = "[\033[1;35mDECMAN\033[m]"
_RED_PREFIX = "\033[91m"
_YELLOW_PREFIX = "\033[93m"
_CYAN_PREFIX = "\033[96m"
_GREEN_PREFIX = "\033[92m"
_GRAY_PREFIX = "\033[90m"
_RESET_SUFFIX = "\033[m"
_SPACING = "    "
_CONTINUATION_PREFIX = f"{_DECMAN_MSG_TAG}{_SPACING} "

INFO = 1
SUMMARY = 2


def print_continuation(msg: str, level: int = SUMMARY):
    """
    Prints a message without a prefix.
    """
    if level == SUMMARY or conf.debug_output or not conf.quiet_output:
        print(f"{_CONTINUATION_PREFIX}{msg}")


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


def print_list(
    msg: str,
    l: list[str],
    elements_per_line: typing.Optional[int] = None,
    max_line_width: typing.Optional[int] = None,
    limit_to_term_size: bool = True,
    level: int = SUMMARY,
):
    """
    Prints a summary message to the user along with a list of elements.

    If the list is empty, prints nothing.
    """
    if len(l) == 0:
        return

    l = l.copy()
    if level == SUMMARY:
        print_summary(msg)
    elif level == INFO:
        print_info(msg)

    print_continuation("", level=level)

    if elements_per_line is None:
        elements_per_line = len(l)

    if max_line_width is None:
        max_line_width = 2**32  # Big enough to basically be unlimited

    if limit_to_term_size:
        max_line_width = (
            shutil.get_terminal_size().columns
            - len(_SPACING)
            - len(_CONTINUATION_PREFIX)
        )

    lines = [f"{l.pop(0)}"]
    index = 0
    elements_in_current_line = 1
    while l:
        next_element = l.pop(0)

        can_fit_elements = elements_in_current_line + 1 <= elements_per_line
        can_fit_text = len(lines[index]) + len(next_element) <= max_line_width

        if can_fit_text and can_fit_elements:
            lines[index] += f" {next_element}"
            elements_in_current_line += 1
        else:
            lines.append(f"{next_element}")
            index += 1
            elements_in_current_line = 1

    for line in lines:
        print_continuation(line, level=level)

    print_continuation("", level=level)


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


def prompt_number(
    msg: str, min_num: int, max_num: int, default: typing.Optional[int] = None
) -> int:
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
        self.source_file: typing.Optional[str] = None
        self.allow_running_source_without_prompt: bool = False
        self.enabled_systemd_units: list[str] = []
        self._enabled_user_systemd_units: list[str] = []
        self.enabled_modules: dict[str, str] = {}
        self.created_files: list[str] = []
        self.pkgbuild_latest_reviewed_commits: dict[str, str] = {}
        self._package_file_cache: dict[str, list[tuple[str, str, int]]] = {}

    def add_enabled_user_systemd_unit(self, user: str, unit: str):
        """
        Stores a user unit as enabled.
        """
        self._enabled_user_systemd_units.append(f"{user}->{unit}")

    def remove_enabled_user_systemd_unit(self, user: str, unit: str):
        """
        Removes a user unit from stored units.
        """
        try:
            self._enabled_user_systemd_units.remove(f"{user}->{unit}")
        except ValueError:
            pass

    def is_systemd_used_unit_enabled(self, user: str, unit: str) -> bool:
        """
        Returns true if the given user unit is stored as enabled.
        """
        return f"{user}->{unit}" in self._enabled_user_systemd_units

    def get_enabled_user_systemd_units(self) -> list[tuple[str, str]]:
        """
        Returns all enabled systemd units.
        """
        result = []
        for unit_str in self._enabled_user_systemd_units:
            unit_l = unit_str.split("->")
            user = unit_l[0]
            unit = unit_l[1]
            result.append((user, unit))
        return result

    def get_package(self, package: str) -> typing.Optional[tuple[str, str]]:
        """
        Returns the latest version and path of a package stored in the built packages cache as a
        tuple (version, path).
        """
        entries = self._package_file_cache.get(package)
        if entries is None:
            return None

        latest_version = None
        latest_path = None
        latest_timestamp = 0

        for entry in entries:
            version, path, timestamp = entry
            if latest_timestamp < timestamp and os.path.exists(path):
                latest_timestamp = timestamp
                latest_version = version
                latest_path = path

        print_debug(f"Latest file for {package} is '{latest_path}'.")

        if latest_path is None:
            return None

        assert latest_version is not None, (
            "If latest_path is set, then latest_version is set."
        )
        return (latest_version, latest_path)

    def add_package_to_cache(self, package: str, version: str, path_to_built_pkg: str):
        """
        Adds a built package to the package file cache. Tries to remove excess cached packages.
        """
        new_entry = (version, path_to_built_pkg, int(time.time()))
        entries = self._package_file_cache.get(package, [])
        for _, already_cached_path, __ in entries:
            if already_cached_path == path_to_built_pkg:
                print_debug(
                    f"Trying to cache {package} version {version}, but the version is already cached: {already_cached_path}"
                )
                return
        entries.append(new_entry)
        self._package_file_cache[package] = entries
        self._clean_pkg_cache(package)

    def _clean_pkg_cache(self, package: str):
        oldest_path = None
        oldest_timestamp = None
        index_of_oldest = None

        entries = self._package_file_cache[package]
        print_debug(f"Package cache has {len(entries)} entries.")

        if len(entries) <= conf.number_of_packages_stored_in_cache:
            print_debug("Old files will not be removed.")
            return

        for index, entry in enumerate(entries):
            _, path, timestamp = entry
            if oldest_timestamp is None or oldest_timestamp > timestamp:
                oldest_timestamp = timestamp
                oldest_path = path
                index_of_oldest = index

        print_debug(f"Oldest cached file for {package} is '{oldest_path}'.")
        if oldest_path is None:
            return
        assert index_of_oldest is not None

        entries.pop(index_of_oldest)
        if os.path.exists(oldest_path):
            print_debug(f"Removing '{oldest_path}' from the package cache.")
            try:
                os.remove(oldest_path)
            except OSError as e:
                print_error(f"{e}")
                print_error(
                    f"Failed to remove file '{oldest_path}' from the package cache."
                )
                print_continuation("You'll have to remove the file manually.")

        self._package_file_cache[package] = entries

    def save(self):
        """
        Writes the store to a file.
        """

        path = os.path.join(_STORE_SAVE_DIR, _STORE_SAVE_FILENAME)

        print_debug(f"Writing Store to '{path}'.")

        d = {
            "source_file": self.source_file,
            "allow_running_source_without_prompt": self.allow_running_source_without_prompt,
            "enabled_systemd_units": self.enabled_systemd_units,
            "enabled_user_systemd_units": self._enabled_user_systemd_units,
            "enabled_modules": self.enabled_modules,
            "created_files": self.created_files,
            "package_file_cache": self._package_file_cache,
            "pkgbuild_git_commits": self.pkgbuild_latest_reviewed_commits,
        }

        try:
            os.makedirs(_STORE_SAVE_DIR, exist_ok=True)
            with open(path, "wt", encoding="utf-8") as file:
                json.dump(d, file)
        except OSError as e:
            print_error(f"{e}")
            raise err.UserFacingError("Failed to save decman store.") from e

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

                store.source_file = d.get("source_file", None)
                store.allow_running_source_without_prompt = d.get(
                    "allow_running_source_without_prompt", False
                )
                store.enabled_systemd_units = d.get(
                    "enabled_systemd_units",
                    [],
                )
                store._enabled_user_systemd_units = d.get(
                    "enabled_user_systemd_units",
                    [],
                )
                store.enabled_modules = d.get("enabled_modules", {})
                store.created_files = d.get("created_files", [])
                store._package_file_cache = d.get("package_file_cache", {})
                store.pkgbuild_latest_reviewed_commits = d.get(
                    "pkgbuild_git_commits",
                    {},
                )

            return store
        except json.JSONDecodeError as e:
            print_error(f"{e}")
            raise err.UserFacingError("Failed to parse decman store json.") from e
        except OSError as e:
            print_error(f"{e}")
            raise err.UserFacingError("Failed to read saved decman store.") from e


class Source:
    """
    Configuration that describes a system.
    """

    def __init__(
        self,
        pacman_packages: set[str],
        aur_packages: set[str],
        user_packages: set[decman.UserPackage],
        ignored_packages: set[str],
        systemd_units: set[str],
        systemd_user_units: dict[str, set[str]],
        files: dict[str, decman.File],
        directories: dict[str, decman.Directory],
        modules: set[decman.Module],
        flatpak_packages: set[str],
        ignored_flatpak_packages: set[str],
    ):
        self.pacman_packages = pacman_packages
        self.aur_packages = aur_packages
        self.user_packages = user_packages
        self.ignored_packages = ignored_packages
        self.systemd_units = systemd_units
        self.systemd_user_units = systemd_user_units
        self.files = files
        self.directories = directories
        self.modules = modules
        self.flatpak_packages = flatpak_packages
        self.ignored_flatpak_packages = ignored_flatpak_packages

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
                module.name, module.version
            ):
                module.after_version_change()
            elif module.enabled and module.name not in store.enabled_modules:
                module.after_version_change()

    def create_all_files(self, only_print: bool) -> list[str]:
        """
        Creates all files and returns them. The files created are based on the specified files,
        directories and modules.
        """
        created_files = []

        def install_files(
            files: dict[str, decman.File],
            variables: typing.Optional[dict[str, str]] = None,
        ):
            for target, file in files.items():
                created_files.append(target)

                if only_print:
                    continue

                try:
                    print_debug(f"Installing file to {target}.")
                    file.copy_to(target, variables)
                except OSError as e:
                    print_error(f"{e}")
                    raise err.UserFacingError(
                        f"Failed to install file to {target}."
                    ) from e

        def install_dirs(
            dirs: dict[str, decman.Directory],
            variables: typing.Optional[dict[str, str]] = None,
        ):
            for target, directory in dirs.items():
                try:
                    print_debug(f"Installing directory to {target}.")
                    created_files.extend(
                        directory.copy_to(target, variables, only_print)
                    )
                except OSError as e:
                    print_error(f"{e}")
                    raise err.UserFacingError(
                        f"Failed to install directory to {target}."
                    ) from e

        install_files(self.files)
        install_dirs(self.directories)

        for module in self.modules:
            if module.enabled:
                install_files(module.files(), module.file_variables())
                install_dirs(module.directories(), module.file_variables())

        return created_files

    def all_file_targets(self) -> list[str]:
        """
        Returns all file targets combined.
        """
        all_files = []
        all_files.extend(self.files.keys())

        for module in self.modules:
            if module.enabled:
                all_files.extend(module.files().keys())

        return all_files

    def all_directory_targets(self) -> list[str]:
        """
        Returns all directory targets combined.
        """
        all_dirs = []
        all_dirs.extend(self.directories.keys())

        for module in self.modules:
            if module.enabled:
                all_dirs.extend(module.directories().keys())

        return all_dirs

    def files_to_remove(self, store: Store, created_files: list[str]) -> list[str]:
        """
        Returns all files that should be removed.
        """
        to_remove = []
        for path in store.created_files:
            if path not in created_files:
                to_remove.append(path)
        return to_remove

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
                if not store.is_systemd_used_unit_enabled(user, unit):
                    entry = result.get(user, [])
                    entry.append(unit)
                    result[user] = entry
        return result

    def user_units_to_disable(self, store: Store) -> dict[str, list[str]]:
        """
        Returns all user systemd units that should be disabled.
        """
        result = {}
        for user, unit in store.get_enabled_user_systemd_units():
            if unit not in self._all_user_units().get(user, set()):
                entry = result.get(user, [])
                entry.append(unit)
                result[user] = entry
        return result

    def packages_to_remove(self, currently_installed_packages: list[str]) -> list[str]:
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
        self, currently_installed_packages: list[str]
    ) -> list[str]:
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
        self, currently_installed_packages: list[str]
    ) -> list[str]:
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

    def flatpak_packages_to_install(
        self, currently_installed_packages: list[str]
    ) -> list[str]:
        """
        Returns all flatpak packages, that are not installed or ignored
        """

        result: list[str] = []
        for pkg in self._all_flatpak_packages():
            if pkg in self.ignored_flatpak_packages:
                continue
            if pkg not in currently_installed_packages:
                result.append(pkg)
        return result

    def flatpak_packages_to_remove(
        self, currently_installed_packages: list[str]
    ) -> list[str]:
        """
        This returns a list of flatpak app ids, that need to be removed since they are installed but not found in either the list of ignored packages or the list of flatpak packages that need to be installed.
        """
        result: list[str] = []
        for package in currently_installed_packages:
            if package in self.ignored_flatpak_packages:
                continue
            if package not in self._all_flatpak_packages():
                result.append(package)

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

    def all_user_pkgs(self) -> set[decman.UserPackage]:
        """
        Returns all active UserPackages.
        """
        result = set()
        result.update(self.user_packages)
        for module in self.modules:
            if module.enabled:
                result.update(module.user_packages())
        return result

    def _all_pacman_pkgs(self) -> set[str]:
        result = set()
        result.update(self.pacman_packages)
        for module in self.modules:
            if module.enabled:
                result.update(module.pacman_packages())
        return result

    def _all_flatpak_packages(self) -> set[str]:
        result = set()
        result.update(self.flatpak_packages)
        for module in self.modules:
            if module.enabled:
                result.update(module.flatpak_packages())

        return result

    def _all_foreign_pkgs(self) -> set[str]:
        result = set()
        result.update(self.aur_packages)
        result.update(map(lambda p: p.pkgname, self.user_packages))
        for module in self.modules:
            if module.enabled:
                result.update(module.aur_packages())
                result.update(map(lambda p: p.pkgname, module.user_packages()))
        return result

    def _all_pkgs(self) -> set[str]:
        result = set()
        result.update(self._all_pacman_pkgs())
        result.update(self._all_foreign_pkgs())
        return result

    def _all_units(self) -> set[str]:
        result = set()
        result.update(self.systemd_units)
        for module in self.modules:
            if module.enabled:
                result.update(module.systemd_units())
        return result

    def _all_user_units(self) -> dict[str, set[str]]:
        result = self.systemd_user_units
        for module in [m for m in self.modules if m.enabled]:
            module_user_units: dict[str, list[str]] = module.systemd_user_units()
            for user in module_user_units.keys():
                if user not in result:
                    result[user] = set()
                result[user].update(module_user_units[user])
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
            packages = (
                subprocess.run(
                    conf.commands.list_pkgs(),
                    check=True,
                    stdout=subprocess.PIPE,
                )
                .stdout.decode()
                .strip()
                .split("\n")
            )
            return packages
        except subprocess.CalledProcessError as error:
            raise err.UserFacingError(
                f"Failed to get installed packages using '{error.cmd}'. Output: {error.stdout}."
            ) from error

    def is_installable(self, dep: str) -> bool:
        """
        Returns True if a dependency can be installed using pacman.
        """
        if dep in self._installable:
            return self._installable[dep]

        result = (
            subprocess.run(
                conf.commands.is_installable(dep), check=False, capture_output=True
            ).returncode
            == 0
        )
        self._installable[dep] = result
        return result

    def get_versioned_foreign_packages(self) -> list[tuple[str, str]]:
        """
        Returns a list of installed packages and their versions that aren't from pacman databases,
        basically AUR packages.
        """
        try:
            output = (
                subprocess.run(
                    conf.commands.list_foreign_pkgs_versioned(),
                    check=True,
                    stdout=subprocess.PIPE,
                )
                .stdout.decode()
                .strip()
                .split("\n")
            )
        except subprocess.CalledProcessError as error:
            raise err.UserFacingError(
                f"Failed to get foreign packages using '{error.cmd}'. Output: {error.stdout}."
            ) from error

        try:
            return [(line.split(" ")[0], line.split(" ")[1]) for line in output]
        except IndexError as error:
            raise err.UserFacingError(
                f"Failed to parse foreign packages from pacman output. Output: {output}"
            ) from error

    def install(self, packages: list[str]):
        """
        Installs the given packages.
        """
        if not packages:
            return

        returncode, output = echo_and_capture_command(
            conf.commands.install_pkgs(packages)
        )
        if returncode != 0:
            raise err.UserFacingError(
                f"Failed to install packages using pacman. Process exited with code {returncode}."
            )
        if conf.print_pacman_output_highlights:
            print_highlighted_pacman_messages(output)

        try:
            subprocess.run(
                conf.commands.set_as_explicitly_installed(packages),
                check=True,
                capture_output=conf.suppress_command_output,
            )
        except subprocess.CalledProcessError as error:
            raise err.UserFacingError(
                "Failed to set packages as explicitly installed using pacman."
            ) from error

    def install_dependencies(self, deps: list[str]):
        """
        Installs the given dependencies.
        """
        if not deps:
            return

        returncode, output = echo_and_capture_command(conf.commands.install_deps(deps))
        if returncode != 0:
            raise err.UserFacingError(
                f"Failed to install packages as dependencies using pacman. Process exited with code {returncode}."
            )
        if conf.print_pacman_output_highlights:
            print_highlighted_pacman_messages(output)

    def install_files(self, files: list[str], as_explicit: list[str]):
        """
        Installs the given files first as dependencies. Then the packages listed in as_explicit are
        installed explicitly.
        """
        if not files:
            return

        returncode, output = echo_and_capture_command(
            conf.commands.install_files(files)
        )
        if returncode != 0:
            raise err.UserFacingError(
                f"Failed to install package files using pacman. Process exited with code {returncode}."
            )
        if conf.print_pacman_output_highlights:
            print_highlighted_pacman_messages(output)

        try:
            if as_explicit:
                subprocess.run(
                    conf.commands.set_as_explicitly_installed(as_explicit),
                    check=True,
                    capture_output=conf.suppress_command_output,
                )
        except subprocess.CalledProcessError as error:
            if conf.suppress_command_output:
                print_error("Output:")
                print_continuation(error.output)
            raise err.UserFacingError(
                "Failed to set packages as explicitly installed using pacman."
            ) from error

    def upgrade(self):
        """
        Upgrades all packages.
        """
        returncode, output = echo_and_capture_command(conf.commands.upgrade())
        if returncode != 0:
            raise err.UserFacingError(
                f"Failed to upgrade packages using pacman. Process exited with code {returncode}."
            )
        if conf.print_pacman_output_highlights:
            print_highlighted_pacman_messages(output)

    def remove(self, packages: list[str]):
        """
        Removes the given packages.
        """
        if not packages:
            return

        returncode, output = echo_and_capture_command(conf.commands.remove(packages))
        if returncode != 0:
            raise err.UserFacingError(
                f"Failed to remove packages using pacman. Process exited with code {returncode}."
            )
        if conf.print_pacman_output_highlights:
            print_highlighted_pacman_messages(output)


def print_highlighted_pacman_messages(output: str):
    """
    Prints lines that contain pacman output keywords.
    """
    print_summary("Pacman output highlights:")
    lines = output.split("\n")
    for index, line in enumerate(lines):
        for keyword in conf.pacman_output_keywords:
            if keyword.lower() in line.lower():
                print_summary(f"lines: {index}-{index + 2}")
                if index >= 1:
                    print_continuation(lines[index - 1])
                print_continuation(line)
                if index + 1 < len(lines):
                    print_continuation(lines[index + 1])
                print_continuation("")

                # Break, as to not print the same line again if it contains multiple keywords
                break


def echo_and_capture_command(program: list[str]) -> tuple[int, str]:
    """
    Runs the given CLI program and arguments.

    Returns a tuple containing the return code of the program as well as all output of the program.
    """

    output = ""

    def read(fd):
        nonlocal output
        buffer = os.read(fd, 1024)
        output += buffer.decode(encoding="utf-8")
        return buffer

    returncode = os.waitstatus_to_exitcode(pty.spawn(program, read))

    return (returncode, output)


class Flatpak:
    def __init__(self) -> None:
        pass

    def get_installed(self) -> list[str]:
        """
        Return all of the installed applications. Dependencies and runtimes are exluded since they will not be explicitly installed and thus flatpak will manage them.
        """
        try:
            packages = (
                subprocess.run(
                    conf.commands.list_flatpak_pkgs(),
                    check=True,
                    stdout=subprocess.PIPE,
                )
                .stdout.decode()
                .strip()
                .split("\n")
            )

            # The header might be included. It might also not. This will make sure that it is not present.
            if "Application ID" in packages:
                packages.remove("Application ID")

            return packages
        except subprocess.CalledProcessError as error:
            raise err.UserFacingError(
                user_facing_msg=f"Failed to get installed flatpak packages using '{error.cmd}'. Output: {error.stdout}."
            ) from error

    def install(self, packages: list[str]):
        """
        Install the listed flatpak packages.
        """
        if not packages:
            return

        returncode, _output = echo_and_capture_command(
            conf.commands.install_flatpak_pkgs(packages)
        )
        if returncode != 0:
            raise err.UserFacingError(
                f"Failed to install flatpak packages. Process exited with code {returncode}."
            )

    def upgrade(self) -> None:
        """
        Upgrade all flatpak packages.
        """
        returncode, _output = echo_and_capture_command(conf.commands.upgrade_flatpak())
        if not returncode == 0:
            raise err.UserFacingError(
                f"Failed to upgrade flatpak packages. Process exited with code {returncode}."
            )

    def remove(self, packages: list[str]):
        """
        Remove all the listed packages and their unused dependecies. This has to happen in two steps.
        """
        if not packages:
            return

        returncode, _output = echo_and_capture_command(
            conf.commands.remove_flatpak(packages)
        )

        if not returncode == 0:
            raise err.UserFacingError(
                f"Failed to remove flatpak packages. Process exited with code {returncode}."
            )

        returncode, _output = echo_and_capture_command(
            conf.commands.remove_unused_flatpak()
        )

        if not returncode == 0:
            raise err.UserFacingError(
                f"Failed to remove unused flatpak packages. Process exited with code {returncode}."
            )


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
        if not units:
            return

        try:
            subprocess.run(
                conf.commands.enable_units(units),
                check=True,
                capture_output=conf.suppress_command_output,
            )
        except subprocess.CalledProcessError as error:
            raise err.UserFacingError(
                f"Failed to enable systemd units: {units}"
            ) from error
        self.state.enabled_systemd_units += units

    def disable_units(self, units: list[str]):
        """
        Disables the given units.
        """
        if not units:
            return

        try:
            subprocess.run(
                conf.commands.disable_units(units),
                check=True,
                capture_output=conf.suppress_command_output,
            )
        except subprocess.CalledProcessError as error:
            raise err.UserFacingError(
                f"Failed to disable systemd units: {units}"
            ) from error
        for unit in units:
            try:
                self.state.enabled_systemd_units.remove(unit)
            except ValueError:
                pass

    def enable_user_units(self, units: list[str], user: str):
        """
        Enables the given units for the given user.
        """
        if not units:
            return

        try:
            subprocess.run(
                conf.commands.enable_user_units(units, user),
                check=True,
                capture_output=conf.suppress_command_output,
            )
        except subprocess.CalledProcessError as error:
            raise err.UserFacingError(
                f"Failed to enable systemd units: {units} for {user}."
            ) from error

        for unit in units:
            self.state.add_enabled_user_systemd_unit(user, unit)

    def disable_user_units(self, units: list[str], user: str):
        """
        Disables the given units for the given user.
        """
        if not units:
            return

        try:
            subprocess.run(
                conf.commands.disable_user_units(units, user),
                check=True,
                capture_output=conf.suppress_command_output,
            )
        except subprocess.CalledProcessError as error:
            raise err.UserFacingError(
                f"Failed to disable systemd units: {units} for {user}."
            ) from error

        for unit in units:
            self.state.remove_enabled_user_systemd_unit(user, unit)
