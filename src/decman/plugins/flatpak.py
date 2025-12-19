import shutil

import decman.core.command as command
import decman.core.error as errors
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store
import decman.plugins as plugins


def packages(fn):
    """
    Annotate that this function returns a set of flatpak package names that should be installed.

    Return type of ``fn``: ``set[str]``
    """
    fn.__flatpak__packages__ = True
    return fn


def user_packages(fn):
    """
    Annotate that this function returns a dict of users and flatpak packages that should be
    installed.

    Return type of ``fn``: ``dict[str, set[str]]``
    """
    fn.__flatpak__user__packages__ = True
    return fn


class Flatpak(plugins.Plugin):
    """
    Plugin that manages flatpak packages added directly to ``packages`` or declared by modules via
    ``@flatpak.packages``. User packages are managed as well.
    """

    NAME = "flatpak"

    def __init__(self) -> None:
        self.packages: set[str] = set()
        self.user_packages: dict[str, set[str]] = {}
        self.ignored_packages: set[str] = set()
        self.commands = FlatpakCommands()

    def available(self) -> bool:
        return shutil.which("flatpak") is not None

    def process_modules(self, store: _store.Store, modules: set[module.Module]):
        # These store keys are used to track changes in modules.
        # This way when these change, module can be marked as changed
        store.ensure("flatpaks_for_module", {})
        store.ensure("user_flatpaks_for_module", {})

        for mod in modules:
            store["flatpaks_for_module"].setdefault(mod.name, set())
            store["user_flatpaks_for_module"].setdefault(mod.name, {})

            packages = plugins.run_method_with_attribute(mod, "__flatpak__packages__") or set()
            user_packages = (
                plugins.run_method_with_attribute(mod, "__flatpak__user__packages__") or {}
            )

            if store["flatpaks_for_module"][mod.name] != packages:
                mod._changed = True
                output.print_debug(
                    f"Module '{mod.name}' set to changed due to modified system flatpaks."
                )

            if store["user_flatpaks_for_module"][mod.name] != user_packages:
                mod._changed = True
                output.print_debug(
                    f"Module '{mod.name}' set to changed due to modified user flatpaks."
                )

            self.packages |= packages
            for user, flatpaks in user_packages.items():
                self.user_packages.setdefault(user, set()).update(flatpaks)

            store["flatpaks_for_module"][mod.name] = packages
            store["user_flatpaks_for_module"][mod.name] = user_packages

    def apply(
        self, store: _store.Store, dry_run: bool = False, params: list[str] | None = None
    ) -> bool:
        pm = FlatpakInterface(self.commands)

        try:
            self.apply_packages(pm, None, self.packages, self.ignored_packages, dry_run)

            for user, packages in self.user_packages.items():
                self.apply_packages(pm, user, packages, self.ignored_packages, dry_run)
        except errors.CommandFailedError as error:
            output.print_error("Running a flatpak command failed.")
            output.print_error(str(error))
            output.print_command_output(error.output)
            output.print_traceback()
            return False
        return True

    def apply_packages(
        self,
        flatpak: "FlatpakInterface",
        user: str | None,
        packages: set[str],
        ignored_packages: set[str],
        dry_run: bool,
    ):
        currently_installed = flatpak.get_apps(user)
        to_remove = currently_installed - packages - ignored_packages
        to_install = packages - currently_installed - ignored_packages

        for_user_msg = f" for {user}" if user else ""

        if to_remove:
            output.print_list(f"Removing flatpak packages{for_user_msg}:", sorted(to_remove))
            if not dry_run:
                flatpak.remove(to_remove, user)

        output.print_summary(f"Upgrading packages{for_user_msg}.")
        if not dry_run:
            flatpak.upgrade(user)

        if to_install:
            output.print_list(f"Installing flatpak packages{for_user_msg}:", sorted(to_install))
            if not dry_run:
                flatpak.install(to_install, user)


class FlatpakCommands:
    def list_apps(self, as_user: bool) -> list[str]:
        """
        Running this command outputs a newline separated list of installed flatpak application IDs.

        If ``as_user`` is ``True``, run the command as the user whose packages should be listed.

        NOTE: The first line says 'Application ID' and should be ignored.
        """
        return [
            "flatpak",
            "list",
            "--app",
            "--user" if as_user else "--system",
            "--columns",
            "application",
        ]

    def install(self, pkgs: set[str], as_user: bool) -> list[str]:
        """
        Running this command installs all listed packages, and their dependencies/runtimes
        automatically.

        If ``as_user`` is ``True``, run the command as the user for whom packages are installed.
        """
        return [
            "flatpak",
            "install",
            "--user" if as_user else "--system",
        ] + sorted(pkgs)

    def upgrade(self, as_user: bool) -> list[str]:
        """
        Updates all installed flatpaks including runtimes and dependencies.

        If ``as_user`` is ``True``, run the command as the user whose flatpaks are updated.
        """
        return [
            "flatpak",
            "update",
            "--user" if as_user else "--system",
        ]

    def remove(self, pkgs: set[str], as_user: bool) -> list[str]:
        """
        Running this command will remove the listed packages.

        If ``as_user`` is ``True``, run the command as the user for whom packages are removed.
        """

        return [
            "flatpak",
            "remove",
            "--user" if as_user else "--system",
        ] + sorted(pkgs)

    def remove_unused(self, as_user: bool) -> list[str]:
        """
        This will remove all unused flatpak dependencies and runtimes.

        If ``as_user`` is ``True``, run the command as the user for whom packages are removed.
        """
        return [
            "flatpak",
            "remove",
            "--unused",
            "--user" if as_user else "--system",
        ]


class FlatpakInterface:
    """
    High level interface for running pacman commands.

    On failure methods raise a ``CommandFailedError``.
    """

    def __init__(self, commands: FlatpakCommands) -> None:
        self._commands = commands

    def get_apps(self, user: str | None = None) -> set[str]:
        """
        Returns a set of installed flatpak apps.

        If ``user`` is set, returns flatpak apps for that user.
        """
        as_user = user is not None

        cmd = self._commands.list_apps(as_user=as_user)
        _, packages_text = command.check_run_result(
            cmd, command.run(cmd, user=user, mimic_login=as_user)
        )
        packages = packages_text.strip().split("\n")

        # In case no apps are installed, the list contains this
        if "" in packages:
            packages.remove("")

        return set(packages)

    def install(self, packages: set[str], user: str | None = None):
        """
        Installs the given packages.

        If ``user`` is set, installs packages for that user.
        """
        if not packages:
            return

        as_user = user is not None

        cmd = self._commands.install(packages, as_user)
        command.check_run_result(cmd, command.pty_run(cmd, user=user, mimic_login=as_user))

    def upgrade(self, user: str | None = None):
        """
        Upgrades all packages.

        If ``user`` is set, upgrades packages for that user.
        """
        as_user = user is not None
        cmd = self._commands.upgrade(as_user)
        command.check_run_result(cmd, command.pty_run(cmd, user=user, mimic_login=as_user))

    def remove(self, packages: set[str], user: str | None = None):
        """
        Removes the given packages as well as unused dependencies.

        If ``user`` is set, removes packages for that user.
        """
        if not packages:
            return

        as_user = user is not None
        cmd = self._commands.remove(packages, as_user)
        command.check_run_result(cmd, command.pty_run(cmd, user=user, mimic_login=as_user))

        cmd = self._commands.remove_unused(as_user)
        command.check_run_result(cmd, command.pty_run(cmd, user=user, mimic_login=as_user))
