import shutil

import decman.core.command as command
import decman.core.module as module
import decman.core.output as output
import decman.core.store as _store
import decman.plugins as plugins


def units(fn):
    """
    Annotate that this function returns a set of systemd unit names that should be enabled.
    """
    fn.__systemd__units__ = True
    return fn


def user_units(fn):
    """
    Annotate that this function returns a dict of users and systemd user unit names that should be
    enabled.
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
        self.enabled_systemd_units: set[str] = set()
        self.enabled_systemd_user_units: dict[str, set[str]] = {}
        self.commands = SystemdCommands()

    def available(self) -> bool:
        return shutil.which("systemctl") is not None

    def process_modules(self, store: _store.Store, modules: set[module.Module]):
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

            if store["systemd_user_units_for_module"][mod.name] != user_units:
                mod._changed = True

            self.enabled_systemd_units |= units
            for user, u_units in user_units.items():
                self.enabled_systemd_user_units.setdefault(user, set()).update(u_units)

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

        for unit in self.enabled_systemd_units:
            if unit not in store["systemd_units"]:
                units_to_enable.add(unit)

        for unit in store["systemd_units"]:
            if unit not in self.enabled_systemd_units:
                units_to_disable.add(unit)

        for user, units in self.enabled_systemd_user_units.items():
            store["systemd_user_units"].setdefault(user, set())
            user_units_to_enable.setdefault(user, set())

            for unit in units:
                if unit not in store["systemd_user_units"][user]:
                    user_units_to_enable[user].add(unit)

        for user, units in store["systemd_user_units"].items():
            self.enabled_systemd_user_units.setdefault(user, set())
            user_units_to_disable.setdefault(user, set())

            for unit in units:
                if unit not in self.enabled_systemd_user_units[user]:
                    user_units_to_disable[user].add(unit)

        output.print_info("Reloading systemd daemon.")
        if not dry_run:
            if not self.reload_daemon():
                return False

        output.print_info("Reloading systemd daemon for users.")
        if not dry_run:
            for user in user_units_to_enable.keys() | user_units_to_disable.keys():
                if not self.reload_user_daemon(user):
                    return False

        output.print_list("Enabling systemd units:", list(units_to_enable))
        if not dry_run:
            if not self.enable_units(store, units_to_enable):
                return False

        output.print_list("Disabling systemd units:", list(units_to_disable))
        if not dry_run:
            if not self.disable_units(store, units_to_disable):
                return False

        for user, units in user_units_to_enable.items():
            output.print_list(f"Enabling systemd units for {user}:", list(units))
            if not dry_run:
                if not self.enable_user_units(store, units, user):
                    return False

        for user, units in user_units_to_disable.items():
            output.print_list(f"Disabling systemd units for {user}:", list(units))
            if not dry_run:
                if not self.disable_user_units(store, units, user):
                    return False

        return True

    def enable_units(self, store: _store.Store, units: set[str]) -> bool:
        """
        Enables the given units.

        Returns ``True`` if the operation was successful.
        """
        if not units:
            return True

        code, text = command.run(self.commands.enable_units(units))
        output.print_command_output(text)
        if code != 0:
            output.print_error(f"Failed to enable systemd units '{' '.join(units)}'.")
            output.print_error(f"Command exited with code: {code}")
            output.print_error(f"{text}")
            return False

        store["systemd_units"] |= units

        return True

    def disable_units(self, store: _store.Store, units: set[str]) -> bool:
        """
        Disables the given units.

        Returns ``True`` if the operation was successful.
        """
        if not units:
            return True

        code, text = command.run(self.commands.disable_units(units))
        output.print_command_output(text)
        if code != 0:
            output.print_error(f"Failed to disable systemd units '{' '.join(units)}'.")
            output.print_error(f"Command exited with code: {code}")
            output.print_error(f"{text}")
            return False

        store["systemd_units"] -= units

        return True

    def enable_user_units(self, store: _store.Store, units: set[str], user: str) -> bool:
        """
        Enables the given units for the given user.

        Returns ``True`` if the operation was successful.
        """
        if not units:
            return True

        code, text = command.run(self.commands.enable_user_units(units, user))
        output.print_command_output(text)
        if code != 0:
            output.print_error(
                f"Failed to enable systemd units '{' '.join(units)}' for user {user}."
            )
            output.print_error(f"Command exited with code: {code}")
            output.print_error(f"{text}")
            return False

        store["systemd_user_units"].setdefault(user, set())
        store["systemd_user_units"][user] |= units

        return True

    def disable_user_units(self, store: _store.Store, units: set[str], user: str) -> bool:
        """
        Disables the given units for the given user.

        Returns ``True`` if the operation was successful.
        """
        if not units:
            return True

        code, text = command.run(self.commands.disable_user_units(units, user))
        output.print_command_output(text)
        if code != 0:
            output.print_error(
                f"Failed to disable systemd units '{' '.join(units)}' for user {user}."
            )
            output.print_error(f"Command exited with code: {code}")
            output.print_error(f"{text}")
            return False

        store["systemd_user_units"].setdefault(user, set())
        store["systemd_user_units"][user] -= units

        return True

    def reload_user_daemon(self, user: str) -> bool:
        """
        Reloads the user's systemd daemon.

        Returns ``True`` if the operation was successful.
        """

        code, text = command.run(self.commands.user_daemon_reload(user))
        output.print_command_output(text)
        if code != 0:
            output.print_error(f"Failed to reload systemd daemon for {user}.")
            output.print_error(f"Command exited with code: {code}")
            output.print_error(f"{text}")
            return False
        return True

    def reload_daemon(self) -> bool:
        """
        Reloads the systemd daemon.

        Returns ``True`` if the operation was successful.
        """

        code, text = command.run(self.commands.daemon_reload())
        output.print_command_output(text)
        if code != 0:
            output.print_error("Failed to reload systemd daemon.")
            output.print_error(f"Command exited with code: {code}")
            output.print_error(f"{text}")
            return False
        return True
