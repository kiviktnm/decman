import re
import shutil
from typing import Callable

import pyalpm

import decman.config as config
import decman.core.command as command
import decman.core.error as errors
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store
import decman.plugins as plugins


def packages(fn):
    """
    Annotate that this function returns a set of pacman package names that should be installed.

    Return type of ``fn``: ``set[str]``
    """
    fn.__pacman__packages__ = True
    return fn


def strip_dependency(dep: str) -> str:
    """
    Removes version spefications from a dependency name.
    """
    rx = re.compile("(=.*|>.*|<.*)")
    return rx.sub("", dep)


class Pacman(plugins.Plugin):
    """
    Plugin that manages pacman packages added directly to ``packages`` or declared by modules via
    ``@packages``.
    """

    NAME = "pacman"

    def __init__(self) -> None:
        self.packages: set[str] = set()
        self.ignored_packages: set[str] = set()
        self.commands = PacmanCommands()
        self.print_highlights = True
        self.keywords = {
            "pacsave",
            "pacnew",
            # These cause too many false positives IMO
            # "warning",
            # "error",
            # "note",
        }
        self.database_signature_level = pyalpm.SIG_DATABASE_OPTIONAL
        self.database_path = "/var/lib/pacman/"

    def available(self) -> bool:
        return shutil.which("pacman") is not None

    def process_modules(self, store: _store.Store, modules: list[module.Module]):
        # This is used to track changes in modules.
        store.ensure("packages_for_module", {})

        for mod in modules:
            store["packages_for_module"].setdefault(mod.name, set())

            packages = plugins.run_method_with_attribute(mod, "__pacman__packages__") or set()

            if store["packages_for_module"][mod.name] != packages:
                mod._changed = True
                output.print_debug(
                    f"Module '{mod.name}' set to changed due to modified pacman packages."
                )

            self.packages |= packages

            store["packages_for_module"][mod.name] = packages

    def apply(
        self, store: _store.Store, dry_run: bool = False, params: list[str] | None = None
    ) -> bool:
        try:
            pm = PacmanInterface(
                self.commands,
                self.print_highlights,
                self.keywords,
                self.database_signature_level,
                self.database_path,
            )

            currently_installed_native = pm.get_native_explicit()
            currently_installed_foreign = pm.get_foreign_explicit()
            orphans = pm.get_native_orphans()
            to_remove = (
                (currently_installed_native | orphans) - self.packages - self.ignored_packages
            )

            actually_to_remove = set()
            to_set_as_dependencies = set()

            dependants_to_keep = self.packages | currently_installed_foreign
            for package in to_remove:
                dependants = pm.get_dependants(package)
                if any(dependant in dependants_to_keep for dependant in dependants):
                    to_set_as_dependencies.add(package)
                else:
                    actually_to_remove.add(package)

            if actually_to_remove:
                output.print_list("Removing pacman packages:", sorted(actually_to_remove))
                if not dry_run:
                    pm.remove(actually_to_remove)

            if to_set_as_dependencies:
                output.print_list(
                    "Setting previously explicitly installed packages as dependencies:",
                    sorted(to_set_as_dependencies),
                )
                if not dry_run:
                    pm.set_as_dependencies(to_set_as_dependencies)

            output.print_summary("Upgrading packages.")
            if not dry_run:
                pm.upgrade()

            to_install = self.packages - currently_installed_native - self.ignored_packages
            output.print_list("Installing pacman packages:", sorted(to_install))

            if not dry_run:
                pm.install(to_install)
        except pyalpm.error as error:
            output.print_error("Failed to query pacman databases with pyalpm.")
            output.print_error(str(error))
            output.print_traceback()
            return False
        except errors.CommandFailedError as error:
            output.print_error(
                "Pacman command exited with an unexpected return code. You may have cancelled a "
                "pacman operation."
            )
            output.print_error(str(error))
            if error.output:
                output.print_command_output(error.output)
            output.print_traceback()
            return False
        return True


class PacmanCommands:
    def list_pacman_repos(self) -> list[str]:
        """
        Running this command prints a newline seperated list of pacman repositories.
        """
        return ["pacman-conf", "--repo-list"]

    def install(self, pkgs: set[str]) -> list[str]:
        """
        Running this command installs the given packages from pacman repositories.
        """
        return ["pacman", "-S", "--needed"] + list(pkgs)

    def upgrade(self) -> list[str]:
        """
        Running this command upgrades all pacman packages from pacman repositories.
        """
        return ["pacman", "-Syu"]

    def set_as_dependencies(self, pkgs: set[str]) -> list[str]:
        """
        Running this command sets the given packages as dependencies.
        """
        return ["pacman", "-D", "--asdeps"] + list(pkgs)

    def set_as_explicit(self, pkgs: set[str]) -> list[str]:
        """
        Running this command sets the given as explicitly installed.
        """
        return ["pacman", "-D", "--asexplicit"] + list(pkgs)

    def remove(self, pkgs: set[str]) -> list[str]:
        """
        Running this command removes the given packages and their dependencies
        (that aren't required by other packages).
        """
        return ["pacman", "-Rs"] + list(pkgs)


class PacmanInterface:
    """
    High level interface for running pacman commands.

    On failure methods raise a ``CommandFailedError`` or ``pyalpm.error``.
    """

    def __init__(
        self,
        commands: PacmanCommands,
        print_highlights: bool,
        keywords: set[str],
        dbsiglevel: int,
        dbpath: str,
    ) -> None:
        self._commands = commands
        self._print_highlights = print_highlights
        self._keywords = keywords
        self._dbsiglevel = dbsiglevel
        self._dbpath = dbpath
        self._handle = self._create_pyalpm_handle()
        self._name_index = self._create_name_index()
        self._provides_index = self._create_provides_index()
        self._requiredby_index = self._create_requiredby_index()

    def _create_pyalpm_handle(self):
        root = "/"

        h = pyalpm.Handle(root, self._dbpath)

        cmd = self._commands.list_pacman_repos()
        repos = command.prg(cmd, pty=False).strip().split("\n")

        # Empty string means no DBs
        if "" in repos and len(repos) == 1:
            return

        for repo in repos:
            h.register_syncdb(repo, self._dbsiglevel)

        return h

    def _create_name_index(self) -> dict[str, pyalpm.Package]:
        return {pkg.name: pkg for db in self._handle.get_syncdbs() for pkg in db.pkgcache}

    def _create_provides_index(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for db in self._handle.get_syncdbs():
            for pkg in db.pkgcache:
                for p in pkg.provides:
                    out.setdefault(strip_dependency(p), set()).add(pkg.name)
                    out.setdefault(p, set()).add(pkg.name)
        return out

    def _create_requiredby_index(self) -> dict[str, set[str]]:
        return {p.name: set(p.compute_requiredby()) for p in self._handle.get_localdb().pkgcache}

    def _is_native(self, package: str) -> bool:
        return package in self._name_index

    def _is_foreign(self, package: str) -> bool:
        return not self._is_native(package)

    def get_native_explicit(self) -> set[str]:
        """
        Returns a set of explicitly installed native packages.
        """
        out: set[str] = set()
        for pkg in self._handle.get_localdb().pkgcache:
            if pkg.reason == pyalpm.PKG_REASON_EXPLICIT and self._is_native(pkg.name):
                out.add(pkg.name)
        return out

        return packages

    def _get_orphans(self, filter_fn: Callable[["PacmanInterface", str], bool]) -> set[str]:
        orphans: set[str] = {
            p.name
            for p in self._handle.get_localdb().pkgcache
            if p.reason == pyalpm.PKG_REASON_DEPEND and filter_fn(self, p.name)
        }

        # Prune orphans until there are only packages that are requiredby other orphans
        changed = True
        while changed:
            changed = False
            for name in tuple(orphans):
                if self._requiredby_index.get(name, set()) - orphans:
                    orphans.remove(name)
                    changed = True
        return orphans

    def get_native_orphans(self) -> set[str]:
        """
        Returns a set of orphaned native packages.
        """
        return self._get_orphans(PacmanInterface._is_native)

    def get_foreign_explicit(self) -> set[str]:
        """
        Returns a set of explicitly installed foreign packages.
        """
        out: set[str] = set()
        for pkg in self._handle.get_localdb().pkgcache:
            if pkg.reason == pyalpm.PKG_REASON_EXPLICIT and not self._is_native(pkg.name):
                out.add(pkg.name)
        return out

    def get_dependants(self, package: str) -> set[str]:
        """
        Returns a set of installed packages that depend on the given package.
        Includes the package itself.
        """
        local = self._handle.get_localdb()

        seen: set[str] = set()
        stack = [package]

        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)

            pkg = local.get_pkg(name)
            if pkg is None:
                continue

            for dep in pkg.compute_requiredby():
                if dep not in seen:
                    stack.append(dep)

        return seen

    def set_as_dependencies(self, packages: set[str]):
        """
        Marks the given packages as dependency packages.
        """
        if not packages:
            return

        cmd = self._commands.set_as_dependencies(packages)
        command.prg(cmd, pty=config.debug_output)

    def install(self, packages: set[str]):
        """
        Installs the given packages. If the packages are already installed, marks them as
        explicitly installed.
        """
        if not packages:
            return

        cmd = self._commands.install(packages)

        pacman_output = command.prg(cmd)
        self.print_highlighted_pacman_messages(pacman_output)

        cmd = self._commands.set_as_explicit(packages)
        command.prg(cmd, pty=config.debug_output)

    def upgrade(self):
        """
        Upgrades all packages.
        """
        cmd = self._commands.upgrade()
        pacman_output = command.prg(cmd)
        self.print_highlighted_pacman_messages(pacman_output)

    def remove(self, packages: set[str]):
        """
        Removes the given packages.
        """
        if not packages:
            return

        cmd = self._commands.remove(packages)
        pacman_output = command.prg(cmd)
        self.print_highlighted_pacman_messages(pacman_output)

    def print_highlighted_pacman_messages(self, pacman_output: str):
        """
        Prints lines that contain pacman output keywords.
        """
        if not self._print_highlights:
            return

        lines = pacman_output.split("\n")
        highlight_lines = []
        for index, line in enumerate(lines):
            for keyword in self._keywords:
                if keyword.lower() in line.lower():
                    highlight_lines.append(f"lines: {index}-{index + 2}")
                    if index >= 1:
                        highlight_lines.append(lines[index - 1])
                    highlight_lines.append(line)
                    if index + 1 < len(lines):
                        highlight_lines.append(lines[index + 1])
                    highlight_lines.append("")

                    # Break, as to not print the same line again if it contains multiple keywords
                    break

        if highlight_lines:
            output.print_summary("Pacman output highlights:")
            for line in highlight_lines:
                if line.startswith("lines:"):
                    output.print_summary(line)
                else:
                    output.print_continuation(line)
