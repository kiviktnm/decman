import os

import decman


class Example(decman.Plugin):
    NAME = "example"

    def available(self) -> bool:
        return os.path.exists("/tmp/example_plugin_available")
