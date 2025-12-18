import os

import decman


class Example(decman.Plugin):
    NAME = "example"

    def available(self) -> bool:
        return os.path.exists("/tmp/example_plugin_available")

    def process_modules(self, store: decman.Store, modules: set[decman.Module]):
        # Toy example for setting modules as changed
        for module in modules:
            module._changed = True

    def apply(
        self, store: decman.Store, dry_run: bool = False, params: list[str] | None = None
    ) -> bool:
        return True
