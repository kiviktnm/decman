# Decman

> THIS README IS FOR AN UNRELEASED VERSION!
>
> There are going to be breaking changes!
> Decman has undergone an architecture rewrite. The new architecture makes decman more expandable and maintainable.
>
> The AUR package will receive this update after I have tested it enough.
> See this [tag](https://github.com/kiviktnm/decman/tree/0.4.2) for the current version of decman available in the AUR.
>
> Migration guide is [here](/docs/migrate-to-v1.md).

Decman is a declarative package & configuration manager for Arch Linux. It allows you to manage installed packages, your dotfiles, enabled systemd units, and run commands automatically. Your system is configured using Python so your configuration can be very adaptive.

## Overview

[See the example for a quick tutorial.](/example/README.md)

To use decman, you need a source file that declares your system installation. I recommend you put this file in source control, for example in a git repository.

`/home/user/config/source.py`:

```py
import decman

from decman import File, Directory

# Declare installed pacman packages
decman.pacman.packages |= {"base", "linux", "linux-firmware", "networkmanager", "ufw", "neovim"}

# Declare installed aur packages
decman.aur.packages |= {"decman"}

# Declare configuration files
# Inline
decman.files["/etc/vconsole.conf"] = File(content="KEYMAP=us")

# From files within your source repository
# (full path here would be /home/user/config/dotfiles/pacman.conf)
decman.files["/etc/pacman.conf"] = File(source_file="./dotfiles/pacman.conf")

# Declare a whole directory
decman.directories["/home/user/.config/nvim"] = Directory(source_directory="./dotfiles/nvim",
                                                          owner="user")
# Ensure that a systemd unit is enabled.
decman.systemd.enabled_units |= {"NetworkManager.service"}
```

To better organize your system configuration, you can create modules.

`/home/user/config/syncthing.py`:

```py
from decman import Module, Store, prg
from decman.plugins import pacman, systemd

# Your custom modules are child classes of the module class.
# They can override methods of the Module-class.
class Syncthing(Module):

    def __init__(self):
        super().__init__(name="syncthing")

    # Run code when a module is first enabled
    def on_enable(self, store: Store):
        # Note: store is a key-value store that will persist between decman runs.
        # You can use it to store your own data as well. Here it is not needed.

        # Call a program
        prg(["ufw", "allow", "syncthing"])

        # Run any python code
        print("Remember to setup syncthing with the browser UI!")

    # On disable is a special method, it will get executed when this module no longer exists.
    # Therefore it must be static, take no parameters, and inline all imports.
    # Imported modules should be available everywhere.
    @staticmethod
    def on_disable():
        # Run code when a module is disabled
        import decman
        decman.prg(["ufw", "deny", "syncthing"])

    # Decorate a function with @pacman.packages to indicate it returns a set of pacman packages
    # to be installed
    @pacman.packages
    def pacman_packages(self) -> set[str]:
        return {"syncthing"}

    # Systemd units are declared in a similiar fashion
    @systemd.user_units
    def systemd_user_units(self) -> dict[str, set[str]]:
        # Systemd user units part of this module
        return {"user": {"syncthing.service"}}
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

For troubleshooting and submitting issues, you should use the `--debug` option.

```sh
sudo decman --debug
```

[See the complete documentation for using decman.](/docs/README.md)

## Installation

Clone the decman PKGBUILD:

```sh
git clone https://aur.archlinux.org/decman.git
```

Review the PKGBUILD and install it.

```sh
cd decman
makepkg -si
```

Remember to add decman to its own configuration.

```py
import decman
decman.aur.packages |= {"decman"}
```

## What decman manages?

Decman has built-in functionality for managing files and directories. Additionally decman manages system state using plugins. By default decman ships with the following plugins:

- [pacman](/docs/pacman.md)
- [systemd](/docs/systemd.md)
- [aur](/docs/aur.md)
- [flatpak](/docs/flatpak.md)

Plugins can be disabled if desired and flatpaks are disabled by default.

Please read the documentation to understand the functionality of those plugins in detail. Here are quick examples to show what the default plugins are capable of.

### Pacman

Pacman plugins manages native packages. Native packages can be installed from the pacman repositories. This plugin will never touch AUR packages.

```py
import decman

# Packages that decman ensures are installed to the system
decman.pacman.packages |= {"firefox", "reflector"}

# These packages will never get installed or removed by decman.
decman.pacman.ignored_packages |= {"opendoas"}
```

### AUR

> [!NOTE]
> Building of AUR or custom packages is not the primary function of decman. There are some issues that I may or may not fix.
> If you can't build a package using decman, consider adding it to `decman.aur.ignored_packages` and building it yourself.

AUR plugins manages foreign packages. Foreign packages are installed from the AUR or other sources. This plugin will never touch native packages.

```py
import decman
from decman.plugins.aur import CustomPackage

# AUR Packages that decman ensures are installed to the system
decman.aur.packages |= {"android-studio", "fnm-bin"}

# These foreign packages will never get installed or removed by decman.
decman.aur.ignored_packages |= {"yay"}

# You can add packages from custom sources.
# Just add a package name and repository / directory containing a PKGBUILD
decman.aur.custom_packages |= {
    CustomPackage("decman", git_url="https://github.com/kiviktnm/decman-pkgbuild.git"),
    CustomPackage("my-own-package", pkgbuild_directory="/path/to/directory/"),
}
```

### Systemd units

> [!NOTE]
> Decman will only enable and disable systemd services. It will not start or stop them.

Decman can enable systemd services, system wide or for a specific user. Decman will enable all units defined in the source, and disable them when they are removed from the source. If a unit is not defined in the source, decman will not touch it.

```py
import decman

# System-wide units
decman.systemd.enabled_units |= {"NetworkManager.service"}

# User specific units
decman.systemd.enabled_user_units.setdefault("user", set()).update({"syncthing.service"})
```

### Flatpak

```py
import decman

# Flatpaks that decman ensures are installed to the system
decman.flatpak.packages |= {"org.mozilla.firefox", "org.signal.Signal"}

# Flatpaks can be installed to specific users only
decman.flatpak.user_packages.setdefault("user", {}).update({"com.valvesoftware.Steam"})

# These flatpaks will never get installed or removed by decman.
decman.flatpak.ignored_packages |= {"dev.zed.Zed"}
```

### Users and PGP keys

Decman ships with built-in modules for managing users, groups and PGP keys. The modules don't support all features. In particular the PGP module is inteded only for AUR packages. However, they still allow managing users declaratively. Read more about them [here](/docs/extras.md).

Here these modules are used to create a `builduser` for AUR packages.

```python
import decman
import os
from decman.extras.gpg import GPGReceiver
from decman.extras.users import User, UserManager

um = UserManager()
gpg = GPGReceiver()

# Add a normal user
um.add_user(User(
    username="alice",
    groups=("libvirt"),
    shell="/usr/bin/fish",
))

# Create builduser
um.add_user(User(
    username="builduser",
    home="/var/lib/builduser",
    system=True,
))

# Receive desired PGP keys to that account (Spotify as an example)
gpg.fetch_key(
    user="builduser",
    gpg_home="/var/lib/builduser/gnupg",
    fingerprint="E1096BCBFF6D418796DE78515384CE82BA52C83A",
    uri="https://download.spotify.com/debian/pubkey_5384CE82BA52C83A.gpg",
)

# Configure aur to use builduser and the GNUPGHOME.
os.environ["GNUPGHOME"] = "/var/lib/builduser/gnupg"
decman.aur.makepkg_user = "builduser"

# Add version control systems required by the packages
decman.pacman.packages |= {"fossil"}

# Add AUR packages that require PGP keys or builduser setup
decman.aur.packages |= {"spotify", "pikchr-fossil"}

decman.modules += [um, gpg]
```

## Managing plugins and the order of operations

The order of operations is managed by setting `decman.execution_order`. This is also the default.

```py
import decman
decman.execution_order = [
    "files",
    "pacman",
    "aur",
    "systemd",
]
```

This variable also manages which plugins are enabled. To enable flatpaks, simply add the plugin to the execution order.

```py
import decman
decman.execution_order = [
    "files",
    "pacman",
    "aur",
    "flatpak",
    "systemd",
]
```

Note that `files` is not a plugin, but is defined here anyways.

Before the core execution order, decman will run hook methods from `Module`s.

1. `before_update`
2. `on_disable`

After the plugin execution, decman will run the following hook methods.

1. `on_enable`
2. `on_change`
3. `atfer_update`

Operations and hooks may be skipped with command line options.

```sh
# Skip the aur plugin
sudo decman --skip aur

# Only apply file operations
sudo decman --no-hooks --only files
```

## Why use decman?

Here are some reasons why I created decman for myself.

### Configuration as documentation

You can consult your config to see what packages are installed and what config files are created. If you organize your config into modules, you also see what files, systemd units and packages are related.

### Modular config

In a modular config, you can also change parts of your system eg. switch shells without it affecting your other setups at all. If you create a module called `Shell` that exposes a function `add_alias`, you can call that function from other modules. Then later if you decide to switch from bash to fish, you can change the internals of your `Shell`-module without modifying your other modules at all.

```py
from decman import Module

# Look below for an example of a theme module
import theme

class Shell(Module):
    def __init__(self):
        super().__init__("shell")
        self._aliases_text = ""

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

import decman

if socket.gethostname() == "laptop":
    # add brightness controls to your laptop
    decman.pacman.packages += ["brightnessctl"]
```

## Alternatives

There are some alternatives you may want to consider instead of using decman.

- [Ansible](https://docs.ansible.com/)
- [aconfmgr](https://github.com/CyberShadow/aconfmgr)
- [NixOS](https://nixos.org/)

### Why not use NixOS?

NixOS is a Linux disto built around the idea of declarative system management, so why create a more limited alternative?

I tried NixOS in the past, but it had some issues that caused me to create decman for Arch Linux instead. In my opinion:

- NixOS forces you to do everything the Nix way.
- NixOS requires learning a new domain specific language.
- NixOS is extreme when it comes to declaration. Sometimes you don't want _everything_ to be managed declaratively.

## License

Copyright (C) 2024-2025 Kivi Kaitaniemi

Decman is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as
published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Decman is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not,
see <https://www.gnu.org/licenses/>.

See [license](LICENSE).
