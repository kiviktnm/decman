import decman
from decman.plugins import aur, pacman


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

    def files(self) -> dict[str, decman.File]:
        return {"/etc/mkinitcpio.conf": decman.File(source_file="./files/mkinitcpio.conf")}

    def on_change(self, store):
        decman.prg(["mkinitcpio", "-P"])
