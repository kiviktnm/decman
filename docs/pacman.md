# Pacman

Pacman plugin can be used to manage pacman packages. The pacman plugin manages only native packages found in arch repositories. All foreign (AUR) packages are ignored by this plugin.

This plugin will ensure that explicitly installed packages match those defined in the decman source. If your system has explicitly installed package A, but it is not included in the source, it will be uninstalled. You don't need to list dependencies in your source as those will be handeled by pacman automatically. However, if you have inluded package B in your source and that package depends on A, this plugin will not remove A. Instead it will demote A to a dependency. This plugin will also remove all orphaned packages automatically.

Please keep in mind that decman doesn't play well with package groups, since all packages part of that group will be installed explicitly. After the initial run decman will now try to remove those packages since it only knows that the group itself should be explicitly installed. Instead of package groups, use meta packages.

## Usage

Define system packages.

```py
import decman
decman.pacman.packages |= {"sudo", "vim"}
```

Define ignored packages. This plugin won't install them nor remove them.

```py
# Include only packages found in the pacman repositories in here.
decman.pacman.ignored_packages |= {"opendoas"}
```

This plugin's execution order step name is `pacman`.

### Within modules

Modules can also define pacman packages. Decorate a module's method with `@decman.plugins.pacman.packages` and return a `set[str]` of package names from that module.

```py
import decman
from decman.plugins import pacman

class MyModule(decman.Module):
    ...

    @pacman.packages
    def packages_defined_in_this_module(self) -> set[str]:
        return {"tmux", "kitty"}
```

If this set changes, this plugin will flag the module as changed. The module's `on_change` method will be executed.

## Configuration

This plugin has a pacman output highlight function. If pacman output contains some keywords, it will be highlighted. You can disable this feature or set the keywords.

```py
import decman

# set keywords
decman.pacman.keywords = {"pacsave", "pacnew", "warning"}

# disable the feature
decman.pacman.print_highlights = False
```

Additionally it's possible to override the commands this plugin uses. Create your own `PacmanCommands` class and override methods returning commands. These are the defaults.

```py
from decman.plugins import pacman

class MyCommands(pacman.PacmanCommands):
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
```

Then set the commands.

```py
import decman
decman.pacman.commands = MyCommands()
```
