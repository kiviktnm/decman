# Migrating to the new architecture

I recommend reading decman's new documentation. This document is supposed to be a quick reference on what will you have to modify in your current source to make it work with the new decman. This will not document new features.

## Few notes about changed behavior

This change is mostly architectural and doesn't change decman's behavior, but there are a few exceptions.

- The pacman plugin will now remove orphan packages
- Explicitly installed packages that are required by other explicitly installed packages are no longer uninstalled when removed from the source.
- Module's `on_disable` will now be executed when the module is no longer present in `decman.modules`.
  - It will be executed even when the module is removed completely from the source
- Order of operations has changed. While the order of operations is now configurable, returning to the previous way is not possible.
- I will no longer provide any examples for using decman with other languages than Python. It would be possible to write an adapter, but I don't see it as worth the effort.

Since there are changes in the internal logic, it is possible that there are more breaking changes, but I haven't thought about them yet.

## Changes

One notable change is replacing lists with sets. Sets make more sense for most things decman manages since duplicates and order are meaningless. With Python you'll want to use `|=` when adding two sets together instead of `+=` which is for lists.

### Files and directories

Files and directories are still managed the same way.

```py
import decman
decman.files["/etc/pacman.conf"] = File(source_file="./dotfiles/pacman.conf")
decman.directories["/home/user/.config/nvim"] = Directory(source_directory="./dotfiles/nvim",
```

### Pacman packages

#### Old

```py
decman.packages += ["devtools", "git", "networkmanager"]
decman.ignored_packages += ["rustup", "yay"]
```

#### New

Packages are now defined with the plugin. Sets are used instead of lists. Ignored packages contains only native packages found in the pacman repositories. Ignored AUR packages is a seperate setting.

```py
decman.pacman.packages |= {"devtools", "git", "networkmanager"}
decman.pacman.ignored_packages |= {"rustup"}
```

### AUR packages

#### Old

```py
decman.aur_packages += ["decman", "android-studio"]
decman.ignored_packages += ["rustup", "yay"]
```

#### New

Packages are now defined with the plugin. Sets are used instead of lists. Ignored packages contains only foreign packages for example AUR packages.

```py
decman.aur.packages |= {"decman", "android-studio"}
decman.aur.ignored_packages |= {"yay"}
```

### User Packages

#### Old

```py
decman.user_packages.append(
    UserPackage(
        pkgname="decman",
        version="0.4.2",
        provides=["decman"],
        dependencies=[
            "python",
            "python-requests",
            "devtools",
            "pacman",
            "systemd",
            "git",
            "less",
        ],
        make_dependencies=[
            "python-setuptools",
            "python-build",
            "python-installer",
            "python-wheel",
        ],
        git_url="https://github.com/kiviktnm/decman-pkgbuild.git",
    )
)
```

#### New

User packages were renamed to custom packages. Sets are used instead of lists. PKGBUILDs are now parsed by decman so defining them is simpler. They are managed by the aur plugin.

```py
from decman.plugins import aur
decman.aur.custom_packages |= {aur.CustomPackage("decman", git_url="https://github.com/kiviktnm/decman-pkgbuild.git")}
```

### Systemd services

#### Old

```py
decman.enabled_systemd_units += ["NetworkManager.service"]
decman.enabled_systemd_user_units.setdefault("kk", []).append("syncthing.service")
```

#### New

Units are now defined with the plugin. Sets are used instead of lists.

```py
decman.systemd.enabled_units |= {"NetworkManager.service"}
decman.systemd.enabled_user_units.setdefault("user", set()).add("syncthing.service")
```

### Flatpaks

#### Old

```py
decman.flatpak_packages += ["org.mozilla.firefox"]
decman.ignored_flatpak_packages += ["org.signal.Signal"]
decman.flatpak_user_packages.setdefault("kk", []).append("com.valvesoftware.Steam")
```

#### New

Packages are now defined with the plugin. Sets are used instead of lists.

```py
decman.flatpak.packages |= {"org.mozilla.firefox"}
decman.flatpak.ignored_packages |= {"org.signal.Signal"}
decman.flatpak.user_packages.setdefault("kk", {}).update({"com.valvesoftware.Steam"})
```

### Changes to modules

#### Old

```py
import decman
from decman import Module, prg, sh

decman.modules += [MyModule()]

class MyModule(Module):
    def __init__(self):
        self.pkgs = ["rust"]
        self.update_rustup = False
        super().__init__(name="Example module", enabled=True, version="1")

    def enable_my_custom_feature(self, b: bool):
        if b:
            self.pkgs = ["rustup"]
            self.update_rustup = True

    def on_enable(self):
        sh("groupadd mygroup")
        prg(["usermod", "--append", "--groups", "mygroup", "kk"])

    def on_disable(self):
        sh("whoami", user="kk")
        sh("echo $HI", env_overrides={"HI": "Hello!"})

    def after_update(self):
        if self.update_rustup:
            prg(["rustup", "update"], user="kk")

    def after_version_change(self):
        prg(["mkinitcpio", "-P"])

    def file_variables(self) -> dict[str, str]:
        return {"%msg%": "Hello, world!"}

    def files(self) -> dict[str, File]:
        return {
            "/usr/local/bin/say-hello": File(
                content="#!/usr/bin/env bash\necho %msg%", permissions=0o755
            ),
            "/usr/local/share/say-hello/image.png": File(
                source_file="files/i-dont-exist.png", bin_file=True
            ),
        }

    def directories(self) -> dict[str, Directory]:
        return {
            "/home/kk/.config/mod-app/": Directory(
                source_directory="files/app-config", owner="kk"
            )
        }

    def pacman_packages(self) -> list[str]:
        return self.pkgs

    def user_packages(self) -> list[UserPackage]:
        return [UserPackage(...)]

    def aur_packages(self) -> list[str]:
        return ["protonvpn"]

    def flatpak_packages(self) -> list[str]:
        return ["org.mozilla.firefox"]

    def flatpak_user_packages(self) -> dict[str, list[str]]:
        return {"username": ["io.github.kolunmi.Bazaar"]}

    def systemd_units(self) -> list[str]:
        return ["reflector.timer"]

    def systemd_user_units(self) -> dict[str, list[str]]:
        return {"kk": ["syncthing.service"]}
```

#### New

`decman.modules` is now a set instead of a list. If you wish to have multiple instances of the same module class, just name them differently. Name needs to be unique accross modules.

Modules no longer have `version`s or `enabled` values. A module is enabled when it gets added to `decman.modules` and disabled when it gets removed from `decman.modules`. Versions are no longer needed because `after_version_change` has been removed and `on_change` has been added. `on_change` is executed automatically after the content of the module changes. `on_disable` will be executed automatically when the module is removed from `decman.modules`. It is no longer a instance method. Instead it must be a self-contained method with no references outside it. Not even imports.

Module methods will get a `Store` instance passed to them as an argument. It can be used to store key-value pairs between decman runs.

Files and directories work the same way as before. Pacman, aur and flatpak packages as well as systemd units have been changed. You'll no longer override methods on the `Module`-class. Instead you'll decorate any method with the appropriate decorator and return desired values from that method.

```py
import decman
from decman import Module, Store, prg, sh
from decman.plugins import pacman, aur, systemd, flatpak

decman.modules |= {MyModule()}

class MyModule(Module):
    def __init__(self):
        self.pkgs = {"rust"}
        self.update_rustup = False
        super().__init__("Example module")

    def enable_my_custom_feature(self, b: bool):
        if b:
            self.pkgs = {"rustup"}
            self.update_rustup = True

    def on_enable(self, store: Store):
        sh("groupadd mygroup")
        prg(["usermod", "--append", "--groups", "mygroup", "kk"])
        store["value"] = True

    @staticmethod
    def on_disable():
        from decman import sh
        sh("whoami", user="kk")
        sh("echo $HI", env_overrides={"HI": "Hello!"})

    def after_update(self, store: Store):
        if self.update_rustup:
            prg(["rustup", "update"], user="kk")

    def on_change(self, store: Store):
        prg(["mkinitcpio", "-P"])

    def file_variables(self) -> dict[str, str]:
        return {"%msg%": "Hello, world!"}

    def files(self) -> dict[str, File]:
        return {
            "/usr/local/bin/say-hello": File(
                content="#!/usr/bin/env bash\necho %msg%", permissions=0o755
            ),
            "/usr/local/share/say-hello/image.png": File(
                source_file="files/i-dont-exist.png", bin_file=True
            ),
        }

    def directories(self) -> dict[str, Directory]:
        return {
            "/home/kk/.config/mod-app/": Directory(
                source_directory="files/app-config", owner="kk"
            )
        }

    @pacman.packages
    def my_pacman_packages(self) -> set[str]:
        return self.pkgs

    @aur.custom_packages
    def my_user_packages(self) -> set[aur.CustomPackage]:
        return [aur.CustomPackage(...)]

    @aur.packages
    def my_aur_packages(self) -> set[str]:
        return {"protonvpn-cli"}

    @flatpak.packages
    def my_flatpak_packages(self) -> set[str]:
        return {"org.mozilla.firefox"}

    @flatpak.user_packages
    def my_flatpak_user_packages(self) -> dict[str, set[str]]:
        return {"username": {"io.github.kolunmi.Bazaar"}}

    @systemd.units
    def my_systemd_units(self) -> set[str]:
        return {"reflector.timer"}

    @systemd.user_units
    def my_systemd_user_units(self) -> dict[str, set[str]]:
        return {"kk": {"syncthing.service"}}
```

## Configuration changes

With the plugin architecture, plugins now contain their own configuration instead of a global `decman.config`. The global `decman.config` still exists but the options available there are much more limited.

### Global options

#### Old

```py
import decman.config

decman.config.debug_output = False
decman.config.suppress_command_output = True
decman.config.quiet_output = False
```

#### New

`suppress_command_output` got removed. Commands that this option affected will now print their output only when encountering errors. In future releases the debug output option will be used to make it available even when not encountering errors.

Other options stayed the same. These will now override values passed as CLI arguments.

```py
decman.config.debug_output = False
decman.config.quiet_output = False
```

### Seperately enabled features

#### Old

```py
decman.config.enable_fpm = True
decman.config.enable_flatpak = False
```

#### New

These options are managed by setting `decman.execution_order`. Add or remove steps as needed.

```py
import decman
decman.execution_order = [
    "files",
    "pacman",
    "aur", # AUR/fpm enabled
    "systemd",
    # "flatpak", # Flatpak disabled
]
```

### Pacman options

#### Old

```py
decman.config.pacman_output_keywords = [
    "pacsave",
    "pacnew",
]
decman.config.print_pacman_output_highlights = True
```

#### New

These are now moved under the pacman plugin and renamed. Keywords is no longer a `list`. It is now a `set`.

```py
import decman
decman.pacman.keywords = {"pacsave", "pacnew"}
decman.pacman.print_highlights = True
```

You'll have to set them for the aur plugin seperately. I recommend sharing the values between the plugins.

```py
import decman
decman.aur.keywords = {"pacsave", "pacnew"}
decman.aur.print_highlights = False
```

### Foreign package management related options

#### Old

```py
decman.config.aur_rpc_timeout = 30
decman.config.makepkg_user = "kk"
decman.config.build_dir = "/tmp/decman/build"
decman.config.pkg_cache_dir = "/var/cache/decman"
decman.config.number_of_packages_stored_in_cache = 3
decman.config.valid_pkgexts = [
    ".pkg.tar",
    ".pkg.tar.gz",
    ".pkg.tar.bz2",
    ".pkg.tar.xz",
    ".pkg.tar.zst",
    ".pkg.tar.lzo",
    ".pkg.tar.lrz",
    ".pkg.tar.lz4",
    ".pkg.tar.lz",
    ".pkg.tar.Z",
]
```

#### New

Options `number_of_packages_stored_in_cache` and `valid_pkgexts` got removed. The default values are no longer configurable. I deemed these settings unnecessary.

`pkg_cache_dir` is now a global setting and is used more generally for all cached things. Package cache is the directory `aur/` in this directory.

```py
decman.config.cache_dir = "/var/cache/decman"
```

Other options are now moved under the aur plugin.

```py
decman.aur.aur_rpc_timeout = 30
decman.aur.makepkg_user = "nobody"
decman.aur.build_dir = "/tmp/decman/build"
```

### Commands

Command management has now also been split up. Instead of a single commands class. Commands have to be overridden seperately for each plugin (except for AUR and pacman).

#### Old

Here are the old defaults.

```py
decman.config.commands = MyCommands()

class MyCommands(decman.config.Commands):
    def list_pkgs(self) -> list[str]:
        return ["pacman", "-Qeq", "--color=never"]

    def list_flatpak_pkgs(self, as_user: bool = False) -> list[str]:
        return [
            "flatpak",
            "list",
            "--app",
            "--user" if as_user else "--system",
            "--columns",
            "application",
        ]

    def list_foreign_pkgs_versioned(self) -> list[str]:
        return ["pacman", "-Qm", "--color=never"]

    def install_pkgs(self, pkgs: list[str]) -> list[str]:
        return ["pacman", "-S", "--color=always", "--needed"] + pkgs

    def install_flatpak_pkgs(self, pkgs: list[str], as_user: bool = False) -> list[str]:
        return ["flatpak", "install", "-y", "--user" if as_user else "--system"] + pkgs

    def install_files(self, pkg_files: list[str]) -> list[str]:
        return ["pacman", "-U", "--color=always", "--asdeps"] + pkg_files

    def set_as_explicitly_installed(self, pkgs: list[str]) -> list[str]:
        return ["pacman", "-D", "--color=always", "--asexplicit"] + pkgs

    def install_deps(self, deps: list[str]) -> list[str]:
        return ["pacman", "-S", "--color=always", "--needed", "--asdeps"] + deps

    def is_installable(self, pkg: str) -> list[str]:
        return ["pacman", "-Sddp", pkg]

    def upgrade(self) -> list[str]:
        return ["pacman", "-Syu", "--color=always"]

    def upgrade_flatpak(self, as_user: bool = False) -> list[str]:
        return [
            "flatpak",
            "update",
            "--noninteractive",
            "-y",
            "--user" if as_user else "--system",
        ]

    def remove(self, pkgs: list[str]) -> list[str]:
        return ["pacman", "-Rs", "--color=always"] + pkgs

    def remove_flatpak(self, pkgs: list[str], as_user: bool = False) -> list[str]:
        return [
            "flatpak",
            "remove",
            "--noninteractive",
            "-y",
            "--user" if as_user else "--system",
        ] + pkgs

    def remove_unused_flatpak(self, as_user: bool = False) -> list[str]:
        return [
            "flatpak",
            "remove",
            "--noninteractive",
            "-y",
            "--unused",
            "--user" if as_user else "--system",
        ]

    def enable_units(self, units: list[str]) -> list[str]:
        return ["systemctl", "enable"] + units

    def disable_units(self, units: list[str]) -> list[str]:
        return ["systemctl", "disable"] + units

    def enable_user_units(self, units: list[str], user: str) -> list[str]:
        return ["systemctl", "--user", "-M", f"{user}@", "enable"] + units

    def disable_user_units(self, units: list[str], user: str) -> list[str]:
        return ["systemctl", "--user", "-M", f"{user}@", "disable"] + units

    def compare_versions(self, installed_version: str, new_version: str) -> list[str]:
        return ["vercmp", installed_version, new_version]

    def git_clone(self, repo: str, dest: str) -> list[str]:
        return ["git", "clone", repo, dest]

    def git_diff(self, from_commit: str) -> list[str]:
        return ["git", "diff", from_commit]

    def git_get_commit_id(self) -> list[str]:
        return ["git", "rev-parse", "HEAD"]

    def git_log_commit_ids(self) -> list[str]:
        return ["git", "log", "--format=format:%H"]

    def review_file(self, file: str) -> list[str]:
        return ["less", file]

    def make_chroot(self, chroot_dir: str, with_pkgs: list[str]) -> list[str]:
        return ["mkarchroot", chroot_dir] + with_pkgs

    def install_chroot_packages(self, chroot_dir: str, packages: list[str]):
        return [
            "arch-nspawn",
            chroot_dir,
            "pacman",
            "-S",
            "--needed",
            "--noconfirm",
        ] + packages

    def resolve_real_name(self, chroot_dir: str, pkg: str) -> list[str]:
        return [
            "arch-nspawn",
            chroot_dir,
            "pacman",
            "-Sddp",
            "--print-format=%n",
            pkg,
        ]

    def remove_chroot_packages(self, chroot_dir: str, packages: list[str]):
        return ["arch-nspawn", chroot_dir, "pacman", "-Rsu", "--noconfirm"] + packages

    def make_chroot_pkg(
        self, chroot_wd_dir: str, user: str, pkgfiles_to_install: list[str]
    ) -> list[str]:
        makechrootpkg_cmd = ["makechrootpkg", "-c", "-r", chroot_wd_dir, "-U", user]

        for pkgfile in pkgfiles_to_install:
            makechrootpkg_cmd += ["-I", pkgfile]

        return makechrootpkg_cmd
```

#### New

AUR and pacman commands are a seperate setting, but they share the same subclass, so it's possible to set them in a one place. New commands have also been added but it is better to look at the plugin documentation for those options. Notable changes are: `list_pkgs` have been split to `list_explicit_native` and `list_explicit_foreign`.

These values are the new defaults.

```py
import decman
from decman.plugins import aur

decman.aur.commands = MyAurAndPacmanCommands()
decman.pacman.commands = MyAurAndPacmanCommands()

class MyAurAndPacmanCommands(aur.AurCommands):
    def list_explicit_native(self) -> list[str]:
        return ["pacman", "-Qeqn", "--color=never"]

    def list_explicit_foreign(self) -> list[str]:
        return ["pacman", "-Qeqm", "--color=never"]

    def list_orphans_native(self) -> list[str]:
        return ["pacman", "-Qndtq", "--color=never"]

    def list_dependants(self, pkg: str) -> list[str]:
        return ["pacman", "-Rc", "--print", "--print-format", "%n", pkg]

    def install(self, pkgs: set[str]) -> list[str]:
        return ["pacman", "-S", "--needed"] + list(pkgs)

    def upgrade(self) -> list[str]:
        return ["pacman", "-Syu"]

    def set_as_dependencies(self, pkgs: set[str]) -> list[str]:
        return ["pacman", "-D", "--asdeps"] + list(pkgs)

    def set_as_explicit(self, pkgs: set[str]) -> list[str]:
        return ["pacman", "-D", "--asexplicit"] + list(pkgs)

    def remove(self, pkgs: set[str]) -> list[str]:
        return ["pacman", "-Rs"] + list(pkgs)

    def list_orphans_foreign(self) -> list[str]:
        return ["pacman", "-Qmdtq", "--color=never"]

    def list_foreign_versioned(self) -> list[str]:
        return ["pacman", "-Qm", "--color=never"]

    def is_installable(self, pkg: str) -> list[str]:
        return ["pacman", "-Sddp", pkg]

    def install_as_dependencies(self, pkgs: set[str]) -> list[str]:
        return ["pacman", "-S", "--needed", "--asdeps"] + list(pkgs)

    def install_files_as_dependencies(self, pkg_files: list[str]) -> list[str]:
        return ["pacman", "-U", "--asdeps"] + pkg_files

    def compare_versions(self, installed_version: str, new_version: str) -> list[str]:
        return ["vercmp", installed_version, new_version]

    def git_clone(self, repo: str, dest: str) -> list[str]:
        return ["git", "clone", repo, dest]

    def git_diff(self, from_commit: str) -> list[str]:
        return ["git", "diff", from_commit]

    def git_get_commit_id(self) -> list[str]:
        return ["git", "rev-parse", "HEAD"]

    def git_log_commit_ids(self) -> list[str]:
        return ["git", "log", "--format=format:%H"]

    def review_file(self, file: str) -> list[str]:
        return ["less", file]

    def make_chroot(self, chroot_dir: str, with_pkgs: set[str]) -> list[str]:
        return ["mkarchroot", chroot_dir] + list(with_pkgs)

    def install_chroot(self, chroot_dir: str, packages: list[str]):
        return [
            "arch-nspawn",
            chroot_dir,
            "pacman",
            "-S",
            "--needed",
            "--noconfirm",
        ] + packages

    def resolve_real_name_chroot(self, chroot_dir: str, pkg: str) -> list[str]:
        return [
            "arch-nspawn",
            chroot_dir,
            "pacman",
            "-Sddp",
            "--print-format=%n",
            pkg,
        ]

    def remove_chroot(self, chroot_dir: str, packages: set[str]):
        return ["arch-nspawn", chroot_dir, "pacman", "-Rsu", "--noconfirm"] + list(packages)

    def make_chroot_pkg(
        self, chroot_wd_dir: str, user: str, pkgfiles_to_install: list[str]
    ) -> list[str]:
        makechrootpkg_cmd = ["makechrootpkg", "-c", "-r", chroot_wd_dir, "-U", user]

        for pkgfile in pkgfiles_to_install:
            makechrootpkg_cmd += ["-I", pkgfile]

        return makechrootpkg_cmd

    def print_srcinfo(self) -> list[str]:
        return ["makepkg", "--printsrcinfo"]
```

Systemd commands:

```py
import decman
from decman.plugins import systemd

decman.systemd.commands = MyCommands()

class MyCommands(SystemdCommands):

    def enable_units(self, units: set[str]) -> list[str]:
        return ["systemctl", "enable"] + list(units)

    def disable_units(self, units: set[str]) -> list[str]:
        return ["systemctl", "disable"] + list(units)

    def enable_user_units(self, units: set[str], user: str) -> list[str]:
        return ["systemctl", "--user", "-M", f"{user}@", "enable"] + list(units)

    def disable_user_units(self, units: set[str], user: str) -> list[str]:
        return ["systemctl", "--user", "-M", f"{user}@", "disable"] + list(units)

    def daemon_reload(self) -> list[str]:
        return ["systemctl", "daemon-reload"]

    def user_daemon_reload(self, user: str) -> list[str]:
        return ["systemctl", "--user", "-M", f"{user}@", "daemon-reload"]
```

Flatpak commands:

```py
import decman
from decman.plugins import flatpak

decman.flatpak.commands = MyCommands()

class MyCommands(FlatpakCommands):
    def list_apps(self, as_user: bool) -> list[str]:
        return [
            "flatpak",
            "list",
            "--app",
            "--user" if as_user else "--system",
            "--columns",
            "application",
        ]

    def install(self, pkgs: set[str], as_user: bool) -> list[str]:
        return [
            "flatpak",
            "install",
            "--user" if as_user else "--system",
        ] + sorted(pkgs)

    def upgrade(self, as_user: bool) -> list[str]:
        return [
            "flatpak",
            "update",
            "--user" if as_user else "--system",
        ]

    def remove(self, pkgs: set[str], as_user: bool) -> list[str]:
        return [
            "flatpak",
            "remove",
            "--user" if as_user else "--system",
        ] + sorted(pkgs)

    def remove_unused(self, as_user: bool) -> list[str]:
        return [
            "flatpak",
            "remove",
            "--unused",
            "--user" if as_user else "--system",
        ]
```
