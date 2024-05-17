# Decman

Decman is a declarative package & configuration manager for Arch Linux. It allows you to manage installed packages, your dotfiles, enabled systemd units, and run commands automatically. Your system is configured using python so your configuration can be very adaptive.

## Overview

A complete example is available in the `example`-directory of this repository. It also serves as documentation so reading it is recommended.

To use decman, you need a source file that declares your system installation. I recommend you put this file in source control, for example in a git repository.

`/home/user/config/source.py`:

```py
import decman
from decman import File, Directory

# Declare installed packages
decman.packages += ["python", "git", "networkmanager", "ufw", "neovim"]

# Declare installed aur packages
decman.aur_packages += ["protonvpn"]

# Declare configuration files
# Inline
decman.files["/etc/vconsole.conf"] = File(content="KEYMAP=us")
# From files within your repository
decman.files["/etc/pacman.conf"] = File(source_file="./dotfiles/pacman.conf")

# Declare a whole directory
decman.directories["/home/user/.config/nvim"] = Directory(source_directory="./dotfiles/nvim",
                                                          owner="user")

# Ensure that a systemd unit is enabled.
decman.enabled_systemd_units += ["NetworkManager.service"]
```

To better organize your system configuration, you can create modules.

`/home/user/config/syncthing.py`:

```py
from decman import Module, prg

# Your custom modules are child classes of the module class.
# They can override methods of the Module-class.
class Syncthing(Module):

    def __init__(self):
        super().__init__(name="syncthing", enabled=True, version="1")

    def on_enable(self):
        # Run code when a module is first enabled

        # Call a program
        prg(["ufw", "allow", "syncthing"])

        # Run any python code
        print("Remember to setup syncthing with the browser UI!")

    def on_disable(self):
        # Run code when a module is disabled
        prg(["ufw", "deny", "syncthing"])

    def pacman_packages(self) -> list[str]:
        # Packages part of this module
        return ["syncthing"]

    def systemd_user_units(self) -> dict[str, list[str]]:
        # Systemd user units part of this module
        return {"user": ["syncthing.service"]}
```

Then import your module in your main source file.

`/home/user/config/source.py`:

```py
import decman
from syncthing import Syncthing

decman.modules += [Syncthing()]
```

Then run decman.

> [!WARNING]
> Decman runs as root. This means that your `source.py` will be executed as root as well.

```sh
sudo decman --source /home/user/config/source.py
```

When you first run decman, you must define the source file, but subsequent runs remember the previous value.

```sh
sudo decman
```

Decman has some CLI options, to see them all run:

```sh
decman --help
```

## Why use decman?

Here are some reasons why I created decman for myself.

### Configuration as documentation

You can consult your config to see what packages are installed and what config files are created. If you organize your config into modules, you also see what files, systemd units and packages are related.

### Modular config

In a modular config, you can also change parts of your system eg. switch shells without it affecting your other setups at all. If you create a module called `Shell` that exposes a function `add_alias`, you can call that function from other modules. Then later if you decide to switch from bash to fish, you can change the internals of your `Shell`-module without modifying your other modules at all.

```py
import theme
class Shell(Module):
    def __init__(self):
        super().__init__("shell", enabled=True, version="1")
        self._aliases_text = ""

    # --

    def add_alias(self, alias: str, cmd: str):
        self._aliases_text += f"alias {alias}='{cmd}'\n"

    def files(self) -> dict[str, File]:
        return {
            "/home/user/.config/fish/config.fish":
            File(source_file="./files/shell/config.fish", owner="user")
        }


    def file_variables(self) -> dict[str, str]:
        fvars = {
            "%aliases%": self._aliases_text,
        }
        # Remember this line when looking at the next point
        fvars.update(theme.COLORS)
        return fvars
```

### Consistency between applications

Decman's file variables are a great way to make sure different tools are in sync. For example, you can create a theme file in your config and then use that theme in modules. The previous `Shell`-module imports a theme from a theme file.

`theme.py`:

```py
COLORS = {
    "%PRIMARY_COLOR%": "#b121ff",
    "%SECONDARY_COLOR%": "#ff5577",
    "%BACKGROUND_COLOR%": "#6a30d5",
    # etc
}
```

### Reproducibility

You can easily reinstall your system using your decman config.

### Dynamic configuration

Using python you can use the same config for different computers and only change some things between them.

```py
import socket

if socket.gethostname() == "laptop":
    # add brightness controls to your laptop
    decman.packages += ["brightnessctl"]
```

### Why not use NixOS?

NixOS is a Linux disto built around the idea of declarative system management, so why create a more limited alternative?

I tried NixOS in the past, but it had some issues that caused me to create decman for Arch Linux instead. In my personal opinion:

- NixOS forces you to do everything the Nix way. Sometimes I just want to develop software without having to use nix tools.
- NixOS is hard, and the documentation (when I last tried it) wasn't that good. Doing more complex stuff was sometimes just very annoying.
- NixOS has unnecessary abstraction with NixOS options. They are great until you have to configure something specific and there is not an option for it. Then you'll have to inline other configuration language within your Nix config. And if some software doesn't have any premade options you'll have to do write the config manually. Then you'll have some software managed with just options and others with normal config files. I prefer to keep everything consistent.

## Installation

Clone the decman PKGBUILD:

```sh
git clone https://github.com/kiviktnm/decman-pkgbuild.git
```

Review the PKGBUILD and install it.

```sh
cd decman-pkgbuild
makepkg -si
```

So far I have not created an AUR package for decman, because I'm not sure if other people would find decman useful.

## What decman manages?

### Packages

Decman can be used to install pacman packages. Decman will install all packages defined in the source and **remove** all packages not defined in the source. You can set packages to be ignored by decman, so that it won't install them nor remove them.

```py
# Include both foreign and pacman packages here.
decman.ignored_packages += ["yay", "opendoas"]
```

### Foreign packages

> [!NOTE]
> Building of foreign packages is not the primary function of decman. There are some issues that I may or may not fix.
> If you can't build a package using decman, consider adding it to `ignored_packages` and building it yourself.

Decman can install AUR packages as well as user defined packages. Foreign packages are AUR and user packages combined.

Here is an example of a user package. Managing user packages is somewhat cumbersome as you have to declare their versions, dependencies and make dependencies manually. However, you probably won't install many user packages anyway.

```py
decman.user_packages.append(
    decman.UserPackage(
        pkgname="decman-git",
        # Note, this example may not be up to date
        version="0.1.0",
        dependencies=["python", "python-requests", "devtools", "pacman", "systemd", "git"],
        make_dependencies=[
            "python-setuptools", "python-build", "python-installer", "python-wheel"
        ],
        git_url="https://github.com/kiviktnm/decman-pkgbuild.git",
    ))
```

Building of foreign packages happens in a chroot. This creates some overhead, but ensures clean builds. Build packages are stored in a cache `/var/cache/decman`. By default decman keeps 3 most recent versions of all packages.

### Systemd units

Decman can enable systemd services, system wide or for a specific user. Decman will enable all units defined in the source, and disable them when they are removed from the source. If a unit is not defined in the source, decman will not touch it.

### Files

Decman functions as a dotfile manager. It will install the defined files and directories to their destinations. You can set file permissions, owners as well as define variables that will be substituted in the installed files. Decman keeps track of all files it creates and when a file is no longer present in your source, it will be also removed from its destination. This helps with keeping your system clean. However, decman won't ever remove directories as they might contain files that weren't created by decman.

### Commands

Modules have 4 methods: `on_enable`, `on_disable`, `after_update` and `after_version_change`. These will be executed if the module is enabled, the module is disabled, after every update and after the version of the module has changed. You can use the helper functions `prg` and `sh` to run programs. These programs could for example be used to update packages managed by another package manager.

## Order of operations

When decman runs, it does the following things in this order.

1. Disable systemd units that are no longer in the source.
1. Create and update files.
1. Remove files no longer in the source.
1. Remove packages not defined in the source.
1. Upgrade packages.
   - To upgrade foreign devel packages (eg. `*-git`) use the `--upgrade-devel` CLI option.
1. Install new packages.
1. Enable new systemd units.
1. Run commands:
   1. `on_enable`
   1. `after_version_change`
   1. `on_disable`
   1. `after_update`

Operations may be skipped with command line options.

## License

Copyright (C) 2024 Kivi Kaitaniemi

Decman is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as
published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Decman is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not,
see <https://www.gnu.org/licenses/>.

See [license](LICENSE).
