import shutil

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

    def available(self) -> bool:
        return shutil.which("pacman") is not None

    def process_modules(self, store: _store.Store, modules: set[module.Module]):
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
        pm = PacmanInterface(self.commands, self.print_highlights, self.keywords)

        try:
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
        except errors.CommandFailedError as error:
            output.print_error("Running a pacman command failed.")
            output.print_error(str(error))
            output.print_command_output(error.output)
            output.print_traceback()
            return False
        return True


class PacmanCommands:
    def list_explicit_native(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of explicitly installed native
        packages.
        """
        return ["pacman", "-Qeqn", "--color=never"]

    def list_explicit_foreign(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of explicitly installed foreign
        packages.
        """
        return ["pacman", "-Qeqm", "--color=never"]

    def list_orphans_native(self) -> list[str]:
        """
        Running this command outputs a newline seperated list of orphaned native packages.
        """
        return ["pacman", "-Qndtq", "--color=never"]

    def list_dependants(self, pkg: str) -> list[str]:
        """
        Running this command outputs a newline seperated list of packages that depend on the given
        package.
        """
        return ["pacman", "-Rc", "--print", "--print-format", "%n", pkg]

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

    On failure methods raise a ``CommandFailedError``.
    """

    def __init__(
        self, commands: PacmanCommands, print_highlights: bool, keywords: set[str]
    ) -> None:
        self._commands = commands
        self._print_highlights = print_highlights
        self._keywords = keywords

    def get_native_explicit(self) -> set[str]:
        """
        Returns a set of explicitly installed native packages.
        """

        cmd = self._commands.list_explicit_native()
        _, packages_text = command.check_run_result(cmd, command.run(cmd))
        packages = set(packages_text.strip().split("\n"))

        return packages

    def get_native_orphans(self) -> set[str]:
        """
        Returns a set of orphaned native packages.
        """

        cmd = self._commands.list_orphans_native()
        rc, packages_text = command.run(cmd)
        # returncode 1 means no packages exist
        if rc == 1:
            return set()
        if rc != 0:
            raise errors.CommandFailedError(cmd, packages_text)

        packages = set(packages_text.strip().split("\n"))

        return packages

    def get_foreign_explicit(self) -> set[str]:
        """
        Returns a set of explicitly installed foreign packages.
        """
        cmd = self._commands.list_explicit_foreign()
        rc, packages_text = command.run(cmd)
        # returncode 1 means no packages exist
        if rc == 1:
            return set()
        if rc != 0:
            raise errors.CommandFailedError(cmd, packages_text)

        packages = set(packages_text.strip().split("\n"))

        return packages

    def get_dependants(self, package: str) -> set[str]:
        """
        Returns a set of packages that depend on the given package.
        """

        cmd = self._commands.list_dependants(package)
        _, packages_text = command.check_run_result(cmd, command.run(cmd))
        packages = set(packages_text.strip().split("\n"))

        return packages

    def set_as_dependencies(self, packages: set[str]):
        """
        Marks the given packages as dependency packages.
        """
        if not packages:
            return

        cmd = self._commands.set_as_dependencies(packages)
        command.check_run_result(cmd, command.run(cmd))

    def install(self, packages: set[str]):
        """
        Installs the given packages. If the packages are already installed, marks them as
        explicitly installed.
        """
        if not packages:
            return

        cmd = self._commands.install(packages)

        _, pacman_output = command.check_run_result(cmd, command.pty_run(cmd))
        self.print_highlighted_pacman_messages(pacman_output)

        cmd = self._commands.set_as_explicit(packages)
        command.check_run_result(cmd, command.run(cmd))

    def upgrade(self):
        """
        Upgrades all packages.
        """
        cmd = self._commands.upgrade()
        _, pacman_output = command.check_run_result(cmd, command.pty_run(cmd))
        self.print_highlighted_pacman_messages(pacman_output)

    def remove(self, packages: set[str]):
        """
        Removes the given packages.
        """
        if not packages:
            return

        cmd = self._commands.remove(packages)
        _, pacman_output = command.check_run_result(cmd, command.pty_run(cmd))
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
