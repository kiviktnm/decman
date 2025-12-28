# Decman documentation

This contains the documentation for decman. Each plugin has its own documentation. For a quick overview of decman, see the [README](/README.md). For a tutorial, see the [example](/example/README.md).

- [pacman](/docs/pacman.md)
- [systemd](/docs/systemd.md)
- [aur](/docs/aur.md)
- [flatpak](/docs/flatpak.md)

Check out [extras](docs/extras.md) for documentation for built-in modules.

## Quick notes

"Decman source" or "source" refers to your system configuration. It is set using the `--source` command line argument with decman.

```sh
sudo decman --source /this/is/your/source.py
```

Decman and decman plugins use sets for most collections to avoid duplicates. Remember to add values to sets instead of reassigning it.

```py
import decman

# GOOD
decman.pacman.packages |= {"vim"}

# BAD, now there is only "vim" in the packages, all previous operations were overridden.
decman.pacman.packages = {"vim"}
```

In Python you should not use from imports with global variables. It can lead to issues.

```py
# DO THIS:
import decman
decman.pacman.packages |= {"vim"}

# THIS MAY NOT WORK
from decman import pacman
pacman.packages |= {"vim"}
```

You can still import classes and functions with from imports safely.

```py
from decman import File
# pacman here refers to the pacman module containing the plugin
# not the plugin instance
from decman.plugins import pacman
```

## Decman Store

Decman stores data in the file `/var/lib/decman/store.json`. This file should not be modified manually. However, if encountering bugs with decman, manual modification may be desirable. The file is JSON so editing it should be easy enough.

Using the store:

```py
# The store is always given as a parameter to a method call.
# You don't need to create new instances.
store["key"] = value

# To ensure that a key exists (with a default value if it doesn't)
store.ensure("my_dict", {})
store["my_dict"]["dict_key"] = 3
```

This store is also available to plugins and modules. The following keys are used by decman:

- `allow_running_source_without_prompt`
- `source_file`
- `enabled_modules`
- `module_on_disable_scripts`
- `all_files`

Details about the keys used by each plugin are provided in the plugin’s documentation.

## Configuring decman

Decman has a small number of configuration options. They are set in your source file with python. These values are prioritized over command line options.

Import the config to modify it.

```py
import decman.config
```

Enable debug messages

```py
decman.config.debug_output = False
```

Disable info messages

```py
decman.config.quiet_output = False
```

Set colored output. This setting should not be used. It should be passed as a command line argument or an environment variable instead.

- Command line argument: `--no-color`
- Environment variables:
  - `NO_COLOR`: disables color
  - `FORCE_COLOR`: enables color

```py
  decman.config.color_output = True
```

Directory for scripts containing Modules' on_disable code

```py
decman.config.module_on_disable_scripts_dir = "/var/lib/decman/scripts/"
```

Cache directory. Plugins like the AUR plugin use this directory as their own cache.

```py
decman.config.cache_dir = "/var/cache/decman"
```

The architecture of the computer's CPU. Currently, this is only used by the AUR plugin, but it may be useful for some other plugins.

```py
decman.config.arch = "x86_64"
```

## Files and directories

Decman functions as a dotfile manager. It will install the defined files and directories to their destinations. You can set file permissions, owners as well as define variables that will be substituted in the installed files. Decman keeps track of all files it creates and when a file is no longer present in your source, it will be also removed from its destination. This helps with keeping your system clean. However, decman won't remove directories as they might contain files that weren't created by decman.

Variables can only be defined for files within modules. See the module example for using file variables.

Files and directories are updated during the `files` execution order step.

### File

Declarative file specification describing how a file should be materialized at a target path.

```py
from decman import File
import decman

# To declare a file, add it's target path and create a File object
decman.files["/home/me/.config/nvim/init.lua"] = File(
    source_file="./dotfiles/nvim/init.lua",
    bin_file=False,
    encoding="utf-8",
    owner="me",
    group="users",
    permissions=0o700,
)
```

Exactly one of `source_file` or `content` must be provided.

The file can be created by copying an existing source file or by writing provided content. For text files, optional variable substitution is applied at copy time. Binary files are copied or written verbatim and never undergo substitution.

Ownership, permissions, and parent directories are enforced on creation. Missing parent directories are created recursively and assigned the same ownership as the file when specified.

#### Parameters:

- `source_file: str`: Path to an existing file to copy from. Mutually exclusive with `content`.
- `content: str`: In-memory file contents to write. Mutually exclusive with `source_file`.
- `bin_file: bool`: If `True`, treat the file as binary. Disables variable substitution and writes bytes verbatim.
- `encoding: str`: Text encoding used when reading or writing non-binary files.
- `owner: str`: System user name to own the file and created parent directories.
- `group: str`: System group name to own the file and created parent directories. By default the `owner`'s group is used.
- `permissions: int`: File mode applied to the target file (e.g. `0o644`).

Note: Variable substitution is a simple string replacement where each key in variables is replaced by its corresponding value. No escaping or templating semantics are applied.

### Directory

Declarative specification for copying the contents of a source directory into a target directory.

```py
from decman import Directory
import decman

# To declare a directory, add it's target path and create a Directory object
decman.directories["/home/me/.config/nvim"] = File(
    source_directory="./dotfiles/nvim",
    bin_files=False,
    encoding="utf-8",
    owner="me",
    group="users",
    permissions=0o600,
)
```

For text files in the directory, optional variable substitution is applied at copy time. Binary files are copied or written verbatim and never undergo substitution.

Ownership, permissions, and parent directories are enforced on creation. Missing parent directories are created recursively and assigned the same ownership as the target directory when specified.

#### Parameters:

- `source_directory: str`: Path to the directory whose contents will be mirrored into the target.
- `bin_files: bool`: If `True`, treat all files as binary. Disables variable substitution and copies bytes verbatim.
- `encoding: str`: Text encoding used when reading or writing non-binary files.
- `owner: str`: System user name to own the files and directories.
- `group: str`: System group name to own the files and directories. By default the `owner`'s group is used.
- `permissions: int`: File mode applied to the created or updated files (e.g. `0o644`).

## Modules

Modules allow grouping related functionality together.

A **Module** is the primary unit for grouping related files, directories, packages, and executable logic in decman. Create your own modules by subclassing `Module`. Then override the methods documented below.

Each module is uniquely identified by its `name`.

Remember to add modules to decman. Modules are added to a list to preserve deterministic execution order for hooks.

```py
import decman
decman.modules += [MyModule()]
```

### Basic Structure

```python
from decman import Module

class MyModule(Module):
    def __init__(self) -> None:
        super().__init__("my-module")
```

### Lifecycle Hooks

Modules can hook into specific phases of a decman run by overriding methods.

#### Before update

Executed **before** any updates are applied.

```python
def before_update(self, store):
    ...
```

#### After update

Executed **after** all updates are applied.

```python
def after_update(self, store):
    ...
```

#### On enable

Executed **once**, when the module transitions from disabled to enabled.

```python
def on_enable(self, store):
    ...
```

#### On change

Executed when the module’s **content changes** between runs. Module's content is deemed changed if:

- If files or directories defined within the module have their content updated
- A plugin marks the module as changed
  - For example, the pacman plugin marks a module as changed if the packages defined within that module change

```python
def on_change(self, store):
    ...
```

#### On disable

Executed when the module is disabled. A module is disabled when it's removed from the modules set.

**Must be declared as `@staticmethod`.**
Validated at class creation time.

```python
@staticmethod
def on_disable():
    import os
    os.remove("/some/file")
```

**Important constraints:**

- Code is copied verbatim into a temporary file
- No external variables
- Imports must be inside the function
- Signature must be exactly `on_disable()`

### Filesystem Declarations

Modules can declaratively define files and directories to be installed.

#### Files

Returns a mapping of target paths to `File` objects.

```python
def files(self) -> dict[str, File]:
    return {
        "/etc/myapp/config.conf": File(source_file="./dotfiles/config.conf"),
    }
```

#### Directories

Returns a mapping of target paths to `Directory` objects.

```python
def directories(self) -> dict[str, Directory]:
    return {
        "/var/lib/myapp": Directory(source_directory="./dotfiles/myapp"),
    }
```

#### File Variable Substitution

Defines variables that are substituted inside **text files** belonging to the module.

```python
def file_variables(self) -> dict[str, str]:
    return {
        "HOSTNAME": "example.com",
        "PORT": "8080",
    }
```

### Extending with plugins

To include plugin functionality inside a module, create a new method and mark it with the plugin's decorator. During the execution of decman, the plugin will call the marked method and use its result. Here is an example with the pacman plugin.

```py
from decman.plugins import pacman

@pacman.packages
def pacman_packages(self) -> set[str]:
    return {"wget", "zip"}
```

## Plugins

Plugins are used to manage a single aspect of a system declaratively. Decman ships with some default plugins useful with Arch Linux but it is possible to add custom plugins.

To manage the execution order of plugins set `decman.execution_order`.

```py
import decman
decman.execution_order = [
    "files", # not a plugin but included here
    "pacman",
    "aur",
    "flatpak",
    "systemd",
]
```

Available plugins are found in `decman.plugins`. You can add your own plugins to that dictionary.

```py
import decman
my_plugin = MyPlugin()
decman.plugins["my-plugin"] = my_plugin

# Remember to include your plugin in the execution order
decman.execution_order += ["my-plugin"]
```

For conveniance, decman provides some plugins with quick access.

```py
import decman

assert decman.pacman == decman.plugins.get("pacman")
assert decman.aur == decman.plugins.get("aur")
assert decman.systemd == decman.plugins.get("systemd")
assert decman.flatpak == decman.plugins.get("flatpak")
```

### Creating custom plugins

Create your own modules by subclassing `Plugin`. Then override the methods documented below.

#### Basic Structure

```python
from decman.plugins import Plugin

class MyPlugin(Plugin):
    # Plugins should be singletons. (Only one instance exists ever.)
    # This name should be the same as the key used in decman.plugins dict.
    NAME = "my-plugin"
```

#### Availability check

Checks if this plugin can be enabled. For example, this could check if a required command is available. Returns `True` if this plugin can be enabled.

This is not useful if the plugin is directly added to `decman.plugins`. However, if using the Python package method for installing plugins, this check is used before adding the plugin automatically to `decman.plugins`.

Please note that this availibility check is executed before **any** decman steps. If a plugin depends on a pacman package, and that package is defined in the source but not yet installed, the plugin will not be available during the first run of decman.

```py
def available(self) -> bool:
    return True
```

#### Process modules

This method gathers state information from modules. If the module's state has changed since the last time running this plugin, set the module to changed. For example, the pacman plugin uses this method to find which modules have methods marked with `@pacman.packages` and calls them.

This method only gathers information. It doesn't apply it.

```py
from decman import Store, Module

def process_modules(self, store: Store, modules: list[Module]):
    ...

    # Toy example for setting modules as changed
    for module in modules:
        module._changed = True
```

#### Apply

Ensures that the state managed by this plugin is present on the system.

`dry_run` indicates that changes should only be printed, not yet applied.

`params` is a list of strings passed as command line arguments. For example running `decman --params abc def` would cause `params = ["abc", "def"]`.

This method must not raise exceptions. Instead it should return `False` to indicate a
failure. The method should handle it's exceptions and print them to the user.

```py
from decman import Store

def apply(
    self, store: Store, dry_run: bool = False, params: list[str] | None = None
) -> bool:
    return True
```

### Installing plugins as Python packages

You can have decman automatically detect plugins by creating a Python package with entry points in `decman.plugins`. Decman also does this with its own plugins.

In `pyproject.toml` set:

```toml
[project.entry-points."decman.plugins"]
pacman = "decman.plugins.pacman:Pacman"
aur = "decman.plugins.aur:AUR"
```

## Useful utilities

Decman ships with some useful utilites that can help with modules and plugins.

### Run commands

Runs a command and returns its output.

```py
import decman
decman.prg(
    ["nvim", "--headless", "+Lazy! sync", "+qa"],
    user = "user",
    env_overrides = {"EXAMPLE": "value"},
    pass_environment = True,
    mimic_login = True,
    pty = True,
    check = True,
)
```

#### Parameters

- `cmd: list[str]`: Command to execute.
- `user: str`: User name to run the command as. If set, the command is executed after dropping privileges to this user.
- `pass_environment: bool`: Copy decman's execution environment variables and pass them to the subprocess.
- `env_overrides: dict[str, str]`: Environment variables to override or add for the command execution. These values are merged on top of the current process environment.
- `mimic_login: bool`: If mimic_login is True, will set the following environment variables according to the given user's passwd file details. This only happens when user is set.
  - `HOME`
  - `USER`
  - `LOGNAME`
  - `SHELL`
- `pty: bool`: If `True`, run the command inside a pseudo-terminal (PTY). This enables interactive behavior and terminal-dependent programs. If `False`, run the command without a PTY using standard subprocess execution.
- `check`: If `True`, raise `decman.core.error.CommandFailedError` when the command exits with a non-zero status. If `False`, print a warning when encountering a non-zero exit code.

### Run a command in a shell

Runs a command in a shell and returns its output. Almost same as `decman.prg` but takes a string argument instead of a list and for example shell redirects are allowed.

```py
import decman
decman.sh(
    "echo $EXAMPLE | less",
    user = "user",
    env_overrides = {"EXAMPLE": "value"},
    mimic_login = True,
    pty = True,
    check = True,
)
```

#### Parameters

- `sh_cmd: str`: Shell command to execute.
- `user: str`: User name to run the command as. If set, the command is executed after dropping privileges to this user.
- `env_overrides dict[str, str]`: Environment variables to override or add for the command execution. These values are merged on top of the current process environment.
- `mimic_login: bool`: If mimic_login is True, will set the following environment variables according to the given user's passwd file details. This only happens when user is set.
  - `HOME`
  - `USER`
  - `LOGNAME`
  - `SHELL`
- `pty: bool`: If `True`, run the command inside a pseudo-terminal (PTY). This enables interactive behavior and terminal-dependent programs. If `False`, run the command without a PTY using standard subprocess execution.
- `check`: If `True`, raise `decman.core.error.CommandFailedError` when the command exits with a non-zero status. If `False`, print a warning when encountering a non-zero exit code.

### Errors

When your source needs to raise an error, decman provides `SourceError`s. Running commands with `prg` and `sh` may raise `decman.core.error.CommandFailedError`s if `check` is set to `True`. These are the errors that should be raised when decman runs your `source.py` file.

```py
import decman
raise decman.SourceError("boom")
```

### Decman Core

Additionally, you can import the modules used by decman. They should be relatively stable and not change too much between decman versions. The module `decman.core.output` is probably the most relevant one, as it provides methods for printing output.
