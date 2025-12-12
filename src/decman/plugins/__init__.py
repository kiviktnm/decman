import importlib.metadata as metadata

import decman.core.module as module


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

    def apply(self, dry_run: bool = False):
        """
        Ensures that the state managed by this plugin is present.

        Set ``dry_run`` to only print changes applying this plugin would cause.
        """

    def process_module(self, module: module.Module):
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
