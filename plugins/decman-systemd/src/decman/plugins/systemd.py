import shutil

import decman.config as config
import decman.core.command as command
import decman.core.error as errors
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store
import decman.plugins as plugins


def units(fn):
    """
    Annotate that this function returns a set of systemd unit names that should be enabled.

    Return type of ``fn``: ``set[str]``
    """
    fn.__systemd__units__ = True
    return fn


def user_units(fn):
    """
    Annotate that this function returns a dict of users and systemd user unit names that should be
    enabled.

    Return type of ``fn``: ``dict[str, set[str]]``
    """
    fn.__systemd__user__units__ = True
    return fn


class SystemdCommands:
    """
    Default commands for the Systemd plugin.
    """

    def enable_units(self, units: set[str]) -> list[str]:
        """
        Running this command enables the given systemd units.
        """
        return ["systemctl", "enable"] + list(units)

    def disable_units(self, units: set[str]) -> list[str]:
        """
        Running this command disables the given systemd units.
        """
        return ["systemctl", "disable"] + list(units)

    def enable_user_units(self, units: set[str], user: str) -> list[str]:
        """
        Running this command enables the given systemd units for the user.
        """
        return ["systemctl", "--user", "-M", f"{user}@", "enable"] + list(units)

    def disable_user_units(self, units: set[str], user: str) -> list[str]:
        """
        Running this command disables the given systemd units for the user.
        """
        return ["systemctl", "--user", "-M", f"{user}@", "disable"] + list(units)

    def daemon_reload(self) -> list[str]:
        """
        Running this command reloads the systemd daemon.
        """
        return ["systemctl", "daemon-reload"]

    def user_daemon_reload(self, user: str) -> list[str]:
        """
        Running this command reloads the systemd daemon for the given user.
        """
        return ["systemctl", "--user", "-M", f"{user}@", "daemon-reload"]


class Systemd(plugins.Plugin):
    NAME = "systemd"

    def __init__(self) -> None:
        self.enabled_units: set[str] = set()
        self.enabled_user_units: dict[str, set[str]] = {}
        self.commands = SystemdCommands()

    def available(self) -> bool:
        return shutil.which("systemctl") is not None

    def process_modules(self, store: _store.Store, modules: list[module.Module]):
        # These store keys are used to track changes in modules.
        # This way when these change, module can be marked as changed
        store.ensure("systemd_units_for_module", {})
        store.ensure("systemd_user_units_for_module", {})

        for mod in modules:
            store["systemd_units_for_module"].setdefault(mod.name, set())
            store["systemd_user_units_for_module"].setdefault(mod.name, {})

            units = plugins.run_method_with_attribute(mod, "__systemd__units__") or set()
            user_units = plugins.run_method_with_attribute(mod, "__systemd__user__units__") or {}

            if store["systemd_units_for_module"][mod.name] != units:
                mod._changed = True
                output.print_debug(
                    f"Module '{mod.name}' set to changed due to modified systemd units."
                )

            if store["systemd_user_units_for_module"][mod.name] != user_units:
                mod._changed = True
                output.print_debug(
                    f"Module '{mod.name}' set to changed due to modified systemd user units."
                )

            self.enabled_units |= units
            for user, u_units in user_units.items():
                self.enabled_user_units.setdefault(user, set()).update(u_units)

            store["systemd_units_for_module"][mod.name] = units
            store["systemd_user_units_for_module"][mod.name] = user_units

    def apply(
        self, store: _store.Store, dry_run: bool = False, params: list[str] | None = None
    ) -> bool:
        store.ensure("systemd_units", set())
        store.ensure("systemd_user_units", {})

        units_to_enable = set()
        units_to_disable = set()
        user_units_to_enable: dict[str, set[str]] = {}
        user_units_to_disable: dict[str, set[str]] = {}

        for unit in self.enabled_units:
            if unit not in store["systemd_units"]:
                units_to_enable.add(unit)

        for unit in store["systemd_units"]:
            if unit not in self.enabled_units:
                units_to_disable.add(unit)

        for user, units in self.enabled_user_units.items():
            store["systemd_user_units"].setdefault(user, set())
            user_units_to_enable.setdefault(user, set())

            for unit in units:
                if unit not in store["systemd_user_units"][user]:
                    user_units_to_enable[user].add(unit)

        for user, units in store["systemd_user_units"].items():
            self.enabled_user_units.setdefault(user, set())
            user_units_to_disable.setdefault(user, set())

            for unit in units:
                if unit not in self.enabled_user_units[user]:
                    user_units_to_disable[user].add(unit)

        try:
            output.print_info("Reloading systemd daemon.")
            if not dry_run:
                self.reload_daemon()

            output.print_info("Reloading systemd daemon for users.")
            if not dry_run:
                for user in user_units_to_enable.keys() | user_units_to_disable.keys():
                    self.reload_user_daemon(user)

            output.print_list("Enabling systemd units:", list(units_to_enable))
            if not dry_run:
                self.enable_units(store, units_to_enable)

            output.print_list("Disabling systemd units:", list(units_to_disable))
            if not dry_run:
                self.disable_units(store, units_to_disable)

            for user, units in user_units_to_enable.items():
                output.print_list(f"Enabling systemd units for {user}:", list(units))
                if not dry_run:
                    self.enable_user_units(store, units, user)

            for user, units in user_units_to_disable.items():
                output.print_list(f"Disabling systemd units for {user}:", list(units))
                if not dry_run:
                    self.disable_user_units(store, units, user)
        except errors.CommandFailedError as error:
            output.print_error("Running a systemd command failed.")
            output.print_error(str(error))
            if error.output:
                output.print_command_output(error.output)
            output.print_traceback()
            return False
        return True

    def enable_units(self, store: _store.Store, units: set[str]):
        """
        Enables the given units.
        """
        if not units:
            return

        cmd = self.commands.enable_units(units)
        command.prg(cmd, pty=config.debug_output)

        store["systemd_units"] |= units

    def disable_units(self, store: _store.Store, units: set[str]):
        """
        Disables the given units.
        """
        if not units:
            return

        cmd = self.commands.disable_units(units)
        command.prg(cmd, pty=config.debug_output)

        store["systemd_units"] -= units

    def enable_user_units(self, store: _store.Store, units: set[str], user: str):
        """
        Enables the given units for the given user.
        """
        if not units:
            return

        cmd = self.commands.enable_user_units(units, user)
        command.prg(cmd, pty=config.debug_output)

        store["systemd_user_units"].setdefault(user, set())
        store["systemd_user_units"][user] |= units

    def disable_user_units(self, store: _store.Store, units: set[str], user: str):
        """
        Disables the given units for the given user.
        """
        if not units:
            return

        cmd = self.commands.disable_user_units(units, user)
        command.prg(cmd, pty=config.debug_output)

        store["systemd_user_units"].setdefault(user, set())
        store["systemd_user_units"][user] -= units

    def reload_user_daemon(self, user: str):
        """
        Reloads the user's systemd daemon.
        """

        cmd = self.commands.user_daemon_reload(user)
        command.prg(cmd, pty=config.debug_output)

    def reload_daemon(self):
        """
        Reloads the systemd daemon.
        """

        cmd = self.commands.daemon_reload()
        command.prg(cmd, pty=config.debug_output)
