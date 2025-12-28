# Flatpak

The flatpak plugin is used to manage flatpak apps. It manages both systemd-wide and user-specific flatpaks. Flatpaks are still a new addition to decman, so they might not work as well as pacman packages. Flatpak management is disabled by default.

This plugin will ensure that installed flatpak apps match those defined in the decman source. If your system has installed a package, but it is not included in the source, it will be uninstalled. You don't need to list dependencies and runtimes in your source as those will be handeled by flatpak automatically. This plugin will remove unneeded runtimes.

## Usage

Define systemd-wide flatpaks.

```py
import decman
decman.flatpak.packages |= {"org.mozilla.firefox", "org.signal.Signal"}
```

Define user-specific flatpaks.

```py
decman.flatpak.user_packages.setdefault("user", {}).update({"com.valvesoftware.Steam"})
```

Define ignored flatpaks. This plugin won't install them nor remove them. This list affects user and system flatpaks.

```py
decman.flatpak.ignored_packages |= {"dev.zed.Zed"}
```

### Within modules

Modules can also define flatpaks units. Decorate a module's method with `@decman.plugins.flatpaks.packages` and return a `set[str]` of flatpak names from that module. For user flatpaks decorate with `@decman.plugins.flatpak.user_packages` and return a `dict[str, set[str]]` of usernames and flatpaks for that user.

```py
import decman
from decman.plugins import flatpak

class MyModule(decman.Module):
    ...

    @flatpak.packages
    def units_defined_in_this_module(self) -> set[str]:
        return {"org.signal.Signal", "org.mozilla.firefox"}

    @flatpak.user_packages
    def user_units_defined_in_this_module(self) -> dict[str, set[str]]:
        return {"user": {"com.valvesoftware.Steam"}}
```

If packages or user packages change, this plugin will flag the module as changed. The module's `on_change` method will be executed.

## Keys used in the decman store

- `flatpaks_for_module`
- `user_flatpaks_for_module`

## Configuration

It's possible to override the commands this plugin uses. Create your own `FlatpakCommands` class and override methods returning commands. These are the defaults.

```py
from decman.plugins import flatpak

class MyCommands(flatpak.FlatpakCommands):
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
```

Then set the commands.

```py
import decman
decman.flatpak.commands = MyCommands()
```
