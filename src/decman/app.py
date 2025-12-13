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

    sys.pycache_prefix = os.path.join(conf.pkg_cache_dir, "python/")

    parser = argparse.ArgumentParser(
        prog="decman",
        description="Declarative package & configuration manager for Arch Linux",
        epilog="See more help at: https://github.com/kiviktnm/decman",
    )

    parser.add_argument("--source", action="store", help="python file containing configuration")
    parser.add_argument(
        "--print",
        "--dry-run",
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
        "--params", nargs="*", type=str, help="additional parameters passed to pluging"
    )

    args = parser.parse_args()

    if os.getuid() != 0:
        output.print_error("Not running as root. Please run decman as root.")
        sys.exit(1)

    original_wd = os.getcwd()
    failed = False

    try:
        with _store.Store(_STORE_FILE, args.dry_run) as store:
            try:
                _execute_source(store, args)
                failed = run_decman(store, args)
            except OSError as error:
                output.print_error(
                    f"Unexpected OSError while running decman: {error.strerror or str(error)}"
                )
                output.print_traceback()
    except errors.SourceError as error:
        output.print_error(f"Error raised manually in the source: {error}")
        output.print_traceback()
    except errors.CommandFailedError as error:
        output.print_error(f"{error}")
        output.print_traceback()
    except errors.InvalidOnDisableError as error:
        output.print_error(f"Invalid source. {error}")
        output.print_traceback()
    except OSError as error:
        output.print_error(f"Failed to access decman store file '{_STORE_FILE}': {error.strerror}.")
        output.print_error("This may cause already completed operations to run again.")
        output.print_traceback()
    except Exception as error:
        output.print_error(f"Unexpected error while running decman: {error}")
        output.print_traceback()
    finally:
        os.chdir(original_wd)

    if failed:
        sys.exit(1)


def run_decman(store: _store.Store, args: argparse.Namespace) -> bool:
    # Ensure execution order is correct. Remove steps not executed now.
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

    # Find newly enabled and disabled modules.
    store.ensure("enabled_modules", [])
    store.ensure("module_on_disable_scripts", {})

    new_modules = []
    disabled_modules = []

    for module in decman.modules:
        if module.name not in store["enabled_modules"]:
            new_modules.append(module.name)

    for module_name in store["enabled_modules"]:
        if module_name not in decman.modules:
            disabled_modules.append(module_name)

    output.print_debug(f"New modules are: {', '.join(new_modules)}.")
    output.print_debug(f"Disabled modules are: {', '.join(disabled_modules)}.")

    # Disable hooks should be run before anything else because they might depend on packages that
    # are going to get removed.
    if not args.no_hooks:
        output.print_summary("Running 'before update' -hooks.")
        for module in decman.modules:
            output.print_info(f"Running 'before update' for {module.name}.")
            if not args.dry_run:
                module.before_update()

        if disabled_modules:
            output.print_summary("Running 'on disable' -scripts.")

        for disabled_module in disabled_modules:
            on_disable_script = store["module_on_disable_scripts"].get(disabled_module, None)
            if on_disable_script:
                output.print_info(f"Running 'on disable' for {disabled_module}.")

                if not args.dry_run:
                    decman.prg([on_disable_script])
                    store["enabled_modules"].remove(disabled_module)
                    store["module_on_disable_scripts"].pop(disabled_module)

    # Run main execution order
    for step in execution_order:
        output.print_debug(f"Running step '{step}'.")
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
                        f"Plugin '{plugin_name}' configured in execution_order\
                         but not found in available plugins."
                    )

    # On enable and on change should be ran last since they might depend on effects caused by
    # execution steps.
    if not args.no_hooks:
        output.print_summary("Running 'on enable' -hooks.")
        for module in decman.modules:
            if module.name in new_modules:
                output.print_info(f"Running 'on enable' for {module.name}.")

                if not args.dry_run:
                    module.on_enable()
                    store["enabled_modules"].append(module.name)
                    try:
                        script = _module.write_on_disable_script(
                            module, conf.module_on_disable_scripts_dir
                        )
                        if script:
                            store["module_on_disable_scripts"][module.name] = script
                    except OSError as error:
                        output.print_error(
                            f"Failed to create 'on disable' script for module {module.name}:\
                            {error.strerror or str(error)}."
                        )
                        output.print_warning(
                            "This script will NOT be created when decman runs the next time."
                        )

        output.print_summary("Running 'on change' -hooks.")
        for module in decman.modules:
            if module._changed:
                output.print_info(f"Running 'on change' for {module.name}.")
                if not args.dry_run:
                    module.on_change()

        output.print_summary("Running 'after update' -hooks.")
        for module in decman.modules:
            output.print_info(f"Running 'after update' for {module.name}.")
            if not args.dry_run:
                module.after_update()

    return True


def _execute_source(store: _store.Store, args: argparse.Namespace):
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
