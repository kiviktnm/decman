import importlib.metadata as metadata

import decman.core.module as module
import decman.core.store as cstore


class Plugin:
    """
    A Plugin manages one part of a system.

    NAME:
        Canonical plugin name.
    """

    NAME: str = ""

    def available(self) -> bool:
        """
        Checks if this plugin can be enabled.

        For example, this could check if a required command is available.

        Returns true if this plugin can be enabled.
        """
        return True

    def apply(
        self, store: cstore.Store, dry_run: bool = False, params: list[str] | None = None
    ) -> bool:
        """
        Ensures that the state managed by this plugin is present.

        Set ``dry_run`` to only print changes applying this plugin would cause.

        This method must not raise exceptions. Instead it should return False to indicate a
        failure. The method should handle it's exceptions and print them to the user.

        Returns ``True`` when applying was successful, ``False`` when it failed.
        """
        return True

    def process_modules(self, store: cstore.Store, modules: set[module.Module]):
        """
        Processes a module.
        """


def available_plugins() -> dict[str, Plugin]:
    """
    Returns all available plugins.
    """
    plugins = {}
    eps = metadata.entry_points(group="decman.plugins")
    for ep in eps:
        cls = ep.load()
        if not issubclass(cls, Plugin):
            continue
        instance = cls()

        if instance.available():
            plugins[cls.NAME] = instance
    return plugins
