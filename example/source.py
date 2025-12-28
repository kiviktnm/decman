from base import BaseModule
from kde import KDE

import decman

decman.pacman.packages |= {"openssh", "qemu-guest-agent", "sudo", "vim"}

decman.modules += [BaseModule(), KDE()]

decman.files["/home/arch/.vimrc"] = decman.File(
    source_file="./files/vimrc", owner="arch", permissions=0o600
)

decman.execution_order = [
    "files",
    "pacman",
    "aur",
    "flatpak",
    "systemd",
]

decman.pacman.packages.add("flatpak")
decman.flatpak.packages |= {"org.mozilla.firefox", "org.signal.Signal"}
