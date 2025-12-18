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
