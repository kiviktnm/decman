# Example

This directory contains an example of a minimal decman configuration. This also functions as a tutorial for starting out with decman. I recommend looking at the [docs](/docs/README.md) after this.

## Tutorial

### Installing decman

I will first install git and base-devel. Then I'll clone the PKGBUILD and install decman.

```sh
sudo pacman -S git base-devel
git clone https://aur.archlinux.org/decman.git
cd decman/
makepkg -sic
```

### Starting out

I will create a source directory for the system's configuration.

```sh
mkdir ~/source
cd ~/source
```

Decman will remove all explicitly installed packages not found in the source. Let's find all explicitly installed packages.

```sh
$ pacman -Qeq
base
base-devel
btrfs-progs
decman
dosfstools
efibootmgr
git
grub
linux
openssh
qemu-guest-agent
sudo
vim
```

First thing to note: `decman` is not a native package. I remember this, but if you don't, you can find only native packages with `pacman -Qeqn` and foreign packages with `pacman -Qeqm`. Since decman is not a native package, the pacman plugin cannot handle it. I'll add decman to AUR packages.

Instead of adding all of these packages to `decman.pacman.packages`, I will first create a module for base system packages in `~/source/base.py`.

```py
import decman
from decman.plugins import pacman, aur

class BaseModule(decman.Module):

    def __init__(self):
        # I'll intend this module to be a singleton (only one instance ever),
        # so I'll inline the module name
        super().__init__("base")

    @pacman.packages
    def pkgs(self) -> set[str]:
        return {
            "base",
            "btrfs-progs",
            "dosfstools",
            "efibootmgr",
            "grub",
            "linux",

            # I'll also include git and base-devel here, they are essential to this system
            "git",
            "base-devel",
        }

    @aur.packages
    def aurpkgs(self) -> set[str]:
        return {"decman"}
```

Then I'll create the main source file with the rest of the packages. I'll import `BaseModule` and add it to `decman.modules`. The main file is `~/source/source.py`.

```py
import decman
from base import BaseModule

decman.pacman.packages |= {"openssh", "qemu-guest-agent", "sudo", "vim"}
decman.modules += [BaseModule()]
```

This config is already enough to run decman for the first time.

```sh
sudo decman --source /home/arch/source/source.py
```

This will run a system upgrade, but otherwise nothing else happens, since my system already matches the desired configuration.

### Extending my config with files and commands

Now I'll want to gradually add more stuff to my config. As an example, I'll add my custom `mkinitcpio.conf`. I'll create the file `~/source/files/mkinitcpio.conf` with the desired content. Then I'll add the file to my `BaseModule`. Since I want to run the command `mkinitcpio -P` every time I update my config, I'll add a on change hook as well. I'll update the file `~/source/base.py`.

```py
class BaseModule(decman.Module):
    ...

    def files(self) -> dict[str, decman.File]:
        return {"/etc/mkinitcpio.conf": decman.File(source_file="./files/mkinitcpio.conf")}

    def on_change(self, store):
        decman.prg(["mkinitcpio", "-P"])
```

I'll also add my vim config to decman. I could now create a Vim module, but since my config is simple, I feel that is not needed. I'll update the main source file `~/source/source.py`.

```py
import decman

...

decman.files["/home/arch/.vimrc"] = decman.File(source_file="./files/vimrc", owner="arch", permissions=0o600)
```

Then I'll apply my changes. Decman will remember my source, so no need to give it as an argument anymore. I don't want to waste time checking for aur updates, so I'll skip them.

```sh
sudo decman --skip aur
```

### Systemd services and flatpaks

I want add a desktop environment. I'll create a module for that in the file `~/source/kde.py`. I'll use SDDM as the login manager. SDDM service needs to be enabled, so I'll use the systemd plugin for that.

```py
import decman
from decman.plugins import pacman, systemd

class KDE(decman.Module):

    def __init__(self):
        super().__init__("kde")

    @pacman.packages
    def pkgs(self) -> set[str]:
        return {
            "plasma-desktop",
            "konsole",
            "sddm",
        }

    @systemd.units
    def units(self) -> set[str]:
        return {"sddm.service"}
```

I'll add the module to enabled modules in `~/source/source.py`.

```py
import decman
from base import BaseModule
from kde import KDE

...

decman.modules += [BaseModule(), KDE()]
```

I'll run decman once again. I'll also start SDDM manually, since decman can't autostart it.

```sh
sudo decman
sudo systemctl start sddm
```

Lastly I want to install some packages with flatpak. I'll first have to install flatpak to make the plugin available. I'll do it manually since it's quicker.

```sh
sudo pacman -S flatpak
```

Then I'll modify `~/source/source.py`. I must add `flatpak` to execution steps to run the plugin.

```py
import decman

...

decman.execution_order = [
    "files",
    "pacman",
    "aur",
    "flatpak",
    "systemd",
]

decman.pacman.packages.add("flatpak")
decman.flatpak.packages |= {"org.mozilla.firefox", "org.signal.Signal"}
```

Then run decman.

```sh
sudo decman
```

### Maintaining a system with decman

Decman is intended to replace your upgrade procedures. Instead of running `yay -Syu` for example, you would run `sudo decman`. With `after_update` hooks you can chain other update commands such as `rustup update`. This way you'll only have to remember to run decman. All other update steps are defined in your source.

## Plugins

It is possible to create your own plugins for decman. However, you probably won't need to do that, as modules are already very capable. This example directory also contains a **very** minimal plugin. To learn more about plugins, look at [the docs](/docs/README.md).
