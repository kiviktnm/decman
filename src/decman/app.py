import argparse
import os
import sys

import decman
import decman.config as conf
import decman.core.error as errors
import decman.core.file_manager as file_manager
import decman.core.module as _module
import decman.core.output as output
import decman.core.store as _store

_STORE_FILE = "/var/lib/decman/store.json"


def main():
    """
    Main entry for the CLI app
    """

    sys.pycache_prefix = os.path.join(conf.cache_dir, "python/")

    parser = argparse.ArgumentParser(
        prog="decman",
        description="Declarative package & configuration manager for Arch Linux",
        epilog="See more help at: https://github.com/kiviktnm/decman",
    )

    parser.add_argument("--source", action="store", help="python file containing configuration")
    parser.add_argument(
        "--dry-run",
        "--print",
        action="store_true",
        default=False,
        help="print what would happen as a result of running decman",
    )
    parser.add_argument("--debug", action="store_true", default=False, help="show debug output")
    parser.add_argument("--skip", nargs="*", type=str, help="skip the following execution steps")
    parser.add_argument(
        "--only", nargs="*", type=str, help="run only the following execution steps"
    )
    parser.add_argument(
        "--no-hooks",
        action="store_true",
        default=False,
        help="don't run hook methods for modules",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="don't print messages with color",
    )
    parser.add_argument(
        "--params", nargs="*", type=str, help="additional parameters passed to plugins"
    )

    args = parser.parse_args()

    conf.debug_output = args.debug

    if args.no_color:
        conf.color_output = False
    else:
        conf.color_output = output.has_ansi_support()

    if os.getuid() != 0:
        output.print_error("Not running as root. Please run decman as root.")
        sys.exit(1)

    original_wd = os.getcwd()
    failed = False

    try:
        with _store.Store(_STORE_FILE, args.dry_run) as store:
            try:
                _execute_source(store, args)
                failed = not run_decman(store, args)
            except errors.SourceError as error:
                output.print_error(f"Error raised manually in the source: {error}")
                output.print_traceback()
                failed = True
            except errors.CommandFailedError as error:
                output.print_error(str(error))
                output.print_traceback()
                failed = True
            except ValueError as error:
                output.print_error("ValueError raised from the source.")
                output.print_error(str(error))
                output.print_traceback()
                failed = True
            except errors.InvalidOnDisableError as error:
                output.print_error(str(error))
                output.print_traceback()
                failed = True
            except Exception as error:
                output.print_error(f"Unexpected error while running decman: {error}")
                output.print_traceback()
                failed = True
    except OSError as error:
        output.print_error(
            f"Failed to access decman store file '{_STORE_FILE}': {error.strerror or str(error)}."
        )
        output.print_error("This may cause already completed operations to run again.")
        output.print_traceback()
    finally:
        os.chdir(original_wd)

    if failed:
        sys.exit(1)


def _execute_source(store: _store.Store, args: argparse.Namespace):
    """
    Runs decman source. May call ``sys.exit(1)`` if user aborts running the source or reading the
    source fails.

    Raises:
        ``SourceError``
            If code in the source raises this error manually.

        ``InvalidOnDisableError``
            If modules in the source have invalid on_disable functions.
    """
    source = store.get("source_file", None)
    source_changed = False

    if args.source is not None:
        source = args.source
        source_changed = True

    if source is None:
        output.print_error(
            "Source was not specified. Please specify a source with the '--source' argument."
        )
        output.print_info("Decman will remember the previously specified source.")
        sys.exit(1)

    if source_changed or not store.get("allow_running_source_without_prompt", False):
        output.print_warning(f"Decman will run the file '{source}' as root!")
        output.print_warning(
            "Only proceed if you trust the file completely. The file can also import other files."
        )

        if not output.prompt_confirm("Proceed?", default=False):
            sys.exit(1)

        if output.prompt_confirm("Remember this choice?", default=False):
            store["allow_running_source_without_prompt"] = True

    source_path = os.path.abspath(source)
    source_dir = os.path.dirname(source_path)
    store["source_file"] = source_path

    try:
        with open(source_path, "rt", encoding="utf-8") as file:
            content = file.read()
    except OSError as error:
        output.print_error(f"Failed to read source '{source_path}': {error.strerror or str(error)}")
        sys.exit(1)

    os.chdir(source_dir)
    sys.path.append(".")
    exec(content)


def run_decman(store: _store.Store, args: argparse.Namespace) -> bool:
    """
    Runs decman with the given arguments and a store.

    Returns ``True`` if executed succesfully. Otherwise ``False``.

    Raises:
        ``SourceError``
            If code in the source raises this error manually.

        ``CommandFailedError``
            If running any command fails.
    """

    store.ensure("enabled_modules", [])
    store.ensure("module_on_disable_scripts", {})

    execution_order = _determine_execution_order(args)
    new_modules = _find_new_modules(store)
    disabled_modules = _find_disabled_modules(store)

    # Disable hooks should be run before anything else because they might depend on packages that
    # are going to get removed.
    if not args.no_hooks:
        _run_before_update(store, args)
        _run_on_disable(store, args, disabled_modules)

    # Run main execution order
    for step in execution_order:
        output.print_info(f"Running step '{step}'.")
        match step:
            case "files":
                if not file_manager.update_files(
                    store, decman.modules, decman.files, decman.directories, dry_run=args.dry_run
                ):
                    return False
            case plugin_name:
                plugin = decman.plugins.get(plugin_name, None)
                if plugin:
                    plugin.process_modules(store, decman.modules)
                    if not plugin.apply(store, dry_run=args.dry_run, params=args.params):
                        return False
                else:
                    output.print_warning(
                        f"Plugin '{plugin_name}' configured in execution_order, "
                        "but not found in available plugins."
                    )

    # On enable and on change should be ran last since they might depend on effects caused by
    # execution steps.
    if not args.no_hooks:
        _run_on_enable(store, args, new_modules)
        _run_on_change(store, args)
        _run_after_update(store, args)

    return True


def _determine_execution_order(args: argparse.Namespace) -> list[str]:
    execution_order = []

    if args.only:
        output.print_debug("Argument '--only' is set. Pruning execution steps.")
        for step in decman.execution_order:
            if step in args.only:
                output.print_debug(f"Adding {step} to execution order.")
                execution_order.append(step)
    else:
        execution_order = decman.execution_order

    for skip in args.skip:
        output.print_debug(f"Skipping step {skip}.")
        execution_order.remove(skip)

    output.print_debug(f"Execution order is: {', '.join(execution_order)}.")
    return execution_order


def _find_new_modules(store: _store.Store):
    new_modules = []
    for module in decman.modules:
        if module.name not in store["enabled_modules"]:
            new_modules.append(module.name)
    output.print_debug(f"New modules are: {', '.join(new_modules)}.")
    return new_modules


def _find_disabled_modules(store: _store.Store):
    disabled_modules = []
    for module_name in store["enabled_modules"]:
        if module_name not in decman.modules:
            disabled_modules.append(module_name)
    output.print_debug(f"Disabled modules are: {', '.join(disabled_modules)}.")
    return disabled_modules


def _run_before_update(store: _store.Store, args: argparse.Namespace):
    output.print_summary("Running before_update -hooks.")
    for module in decman.modules:
        output.print_info(f"Running before_update for {module.name}.")
        if not args.dry_run:
            module.before_update(store)


def _run_on_disable(store: _store.Store, args: argparse.Namespace, disabled_modules: list[str]):
    if not disabled_modules:
        return

    output.print_summary("Running on_disable -scripts.")

    for disabled_module in disabled_modules:
        on_disable_script = store["module_on_disable_scripts"].get(disabled_module, None)
        if on_disable_script:
            output.print_info(f"Running on_disable for {disabled_module}.")

            if not args.dry_run:
                decman.prg([on_disable_script])
                store["enabled_modules"].remove(disabled_module)
                store["module_on_disable_scripts"].pop(disabled_module)


def _run_on_enable(store: _store.Store, args: argparse.Namespace, new_modules: list[str]):
    if not new_modules:
        return

    output.print_summary("Running on_enable -hooks.")
    for module in decman.modules:
        if module.name in new_modules:
            output.print_info(f"Running on_enable for {module.name}.")

            if not args.dry_run:
                module.on_enable(store)
                store["enabled_modules"].append(module.name)
                try:
                    script = _module.write_on_disable_script(
                        module, conf.module_on_disable_scripts_dir
                    )
                    if script:
                        store["module_on_disable_scripts"][module.name] = script
                except OSError as error:
                    output.print_error(
                        f"Failed to create on_disable script for module {module.name}: "
                    )
                    output.print_error(f"{error.strerror or str(error)}.")
                    output.print_traceback()
                    output.print_warning(
                        "This script will NOT be created when decman runs the next time."
                    )
                    output.print_warning(
                        "You should investigate the reason for the error and try to fix it."
                    )
                    output.print_warning(
                        "Then disable and re-enable this module to create the script."
                    )


def _run_on_change(store: _store.Store, args: argparse.Namespace):
    output.print_summary("Running on_change -hooks.")
    for module in decman.modules:
        if module._changed:
            output.print_info(f"Running on_change for {module.name}.")
            if not args.dry_run:
                module.on_change(store)


def _run_after_update(store: _store.Store, args: argparse.Namespace):
    output.print_summary("Running after_update -hooks.")
    for module in decman.modules:
        output.print_info(f"Running after_update for {module.name}.")
        if not args.dry_run:
            module.after_update(store)
