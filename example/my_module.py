# from import is ok for importing classes and functions
# just remember to not import variables this way
from decman import Module, sh

import decman


class MyModule(Module):

    def __init__(self):
        self.pkgs = ["rust"]
        super().__init__("Example module", True, "1")

    def enable_my_custom_feature(self, b: bool):
        if b:
            self.pkgs = ["rustup"]

    def pacman_packages(self) -> list[str]:
        return self.pkgs
