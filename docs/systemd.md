# Systemd

The systemd plugin can enable systemd services, system wide or for a specific user. It will enable all units defined in the source, and disable them when they are removed from the source.

This plugin manages systemd units "softly". It only touches units included in the source. So if you install a package that automatically enables a systemd unit, you don't have to include it in the source. If a unit is not defined in the source, the plugin will not touch it.

Decman will only enable and disable systemd services. It will not start or stop them. Starting or stopping them automatically can cause issues.

## Usage

Declare system-wide units.

```py
import decman
decman.systemd.enabled_units |= {"NetworkManager.service", "ufw.service"}
```

Declare user units. Here this `setdefault` method is used to ensure that the key `user` exists. In this case you cannot use the `|=` syntax and instead must call the `update`-method.

```py
decman.systemd.enabled_user_units.setdefault("user", set()).update({"syncthing.service"})
```

This plugin's execution order step name is `systemd`.

### Within modules

Modules can also define systemd units. Decorate a module's method with `@decman.plugins.systemd.units` and return a `set[str]` of package names from that module. For user units decorate with `@decman.plugins.systemd.user_units` and return a `dict[str, set[str]]` of usernames and user units.

```py
import decman
from decman.plugins import systemd

class MyModule(decman.Module):
    ...

    @systemd.units
    def units_defined_in_this_module(self) -> set[str]:
        return {"NetworkManager.service", "ufw.service"}

    @systemd.user_units
    def user_units_defined_in_this_module(self) -> dict[str, set[str]]:
        return {"user": {"syncthing.service"}}
```

If units or user units change, this plugin will flag the module as changed. The module's `on_change` method will be executed.

## Configuration

It's possible to override the commands this plugin uses. Create your own `SystemdCommands` class and override methods returning commands. These are the defaults.

```py
from decman.plugins import systemd

class MyCommands(systemd.SystemdCommands):
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
```

Then set the commands.

```py
import decman
decman.systemd.commands = MyCommands()
```
