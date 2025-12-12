# Commands used in development

Before committing ensure all tests pass and format files.

## Running

Run decman as root to test all changes:

```sh
sudo uv run decman
```

## Testing

Run all unit tests (`-s` disables output capturing):

```sh
uv run pytest -s
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
