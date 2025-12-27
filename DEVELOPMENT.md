# Commands used in development

Before committing ensure all tests pass and format files.

## Running

Run decman as root to test all changes:

```sh
sudo uv run --all-packages decman
```

## Python shell

Running a python shell with all the packages.

```sh
sudo uv run --all-packages python
sudo uv run --exact --package decman python
```

## Testing

Run all unit tests (`-s` disables output capturing, needed for PTY test):

```sh
uv run --package decman pytest -s tests/
uv run --package decman-pacman pytest packages/decman-pacman/tests/
uv run --package decman-systemd pytest packages/decman-systemd/tests/
uv run --package decman-flatpak pytest packages/decman-flatpak/tests/
```

## Formatting

Format all files:

```sh
uv run ruff format
```

## Linting

Run lints:

```sh
uv run ruff check
```

Apply fixes:

```sh
uv run ruff check --fix
```

## Installing the example plugin

```sh
uv pip install -e example/plugin/
```

Uninstalling:

```sh
uv pip uninstall decman-plugin-example
```

Making the plugin available/unavailable:

```sh
touch /tmp/example_plugin_available
rm /tmp/example_plugin_available
```
