import builtins
import dis
import inspect
import os
import textwrap
import types
import typing

import decman.core.error as errors
import decman.core.fs as fs


class Module:
    """
    Unit for organizing related files, packages and other configuration.

    Inherit this class to create your own modules.

    Parameters:
        name:
            The name of the module. It must be unique.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._changed = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        m = cls.__dict__.get("on_disable")
        if m is None:
            return

        if not isinstance(m, staticmethod):
            raise errors.InvalidOnDisableError(
                f"{cls.__module__}.{cls.__name__}",
                "on_disable must be declared as @staticmethod",
            )

        func = m.__func__

        _validate_on_disable(f"{cls.__module__}.{cls.__name__}", func)

    def before_update(self):
        """
        Override this method to run python code before updating the system.

        Handle errors within this function. If an error should abort running decman,
        raise SourceError or CommandFailedError.
        """

    def after_update(self):
        """
        Override this method to run python code after updating the system.

        Handle errors within this function. If an error should abort running decman,
        raise SourceError or CommandFailedError.
        """

    def on_enable(self):
        """
        Override this method to run python code when this module gets enabled.

        Handle errors within this function. If an error should abort running decman,
        raise SourceError or CommandFailedError.
        """

    def on_change(self):
        """
        Override this method to run python code after the contents of this module have been
        changed in the source.

        Handle errors within this function. If an error should abort running decman,
        raise SourceError or CommandFailedError.
        """

    @staticmethod
    def on_disable():
        """
        Override this method to run python code when this module gets disabled.

        This code will get copied *as is* to a temporary file. Do not use external variables or
        imports. If you must use imports, define them inside this method.
        """

    def files(self) -> dict[str, fs.File]:
        """
        Override this method to return files that should be installed as a part of this module.
        """
        return {}

    def directories(self) -> dict[str, fs.Directory]:
        """
        Override this method to return directories that should be installed as a part of this
        module.
        """
        return {}

    def file_variables(self) -> dict[str, str]:
        """
        Override this method to return variables that should replaced with a new value inside
        this module's text files.
        """
        return {}

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and other.name == self.name


def write_on_disable_script(mod_obj: Module, out_dir: str) -> str | None:
    """
    Writes a on_disable script for the given module. Returns the path to that script.

    Raises:
        OSError
            If creating the script file fails.
    """
    cls: typing.Type[Module] = type(mod_obj)

    # Get the descriptor so we can unwrap staticmethod
    desc = cls.__dict__.get("on_disable")
    if desc is None:
        return None

    # unwrap staticmethod to get the real function
    if isinstance(desc, staticmethod):
        func = desc.__func__
    else:
        func = desc  # already a function

    src = inspect.getsource(func)
    src = textwrap.dedent(src)

    # Build a standalone script that defines the function and calls it
    script = f"""#!/usr/bin/env python3
# generated from {cls.__module__}.{cls.__name__}.on_disable

{src}

if __name__ == "__main__":
    {func.__name__}()
"""
    script_file = fs.File(content=script, permissions=0o755)
    script_path = os.path.join(out_dir, f"{mod_obj.name}_on_disable.py")
    script_file.copy_to(script_path)
    return script_path


def _iter_code_objects(code: types.CodeType):
    yield code
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from _iter_code_objects(const)


def _validate_on_disable(module_type: str, func: types.FunctionType) -> None:
    # No args
    if inspect.signature(func).parameters:
        raise errors.InvalidOnDisableError(module_type, "on_disable must take no parameters")

    bad_names: set[str] = set()

    for code in _iter_code_objects(func.__code__):
        # No closures anywhere (outer or nested)
        if code.co_freevars:
            raise errors.InvalidOnDisableError(
                module_type, "on_disable must not close over outer variables"
            )

        # No non-builtin globals / nonlocals anywhere
        for ins in dis.get_instructions(code):
            if ins.opname in ("LOAD_GLOBAL", "LOAD_DEREF"):
                name = ins.argval
                if not hasattr(builtins, name):
                    bad_names.add(name)

    if bad_names:
        raise errors.InvalidOnDisableError(
            module_type,
            f"on_disable uses nonlocal/global names: {', '.join(sorted(bad_names))}",
        )
