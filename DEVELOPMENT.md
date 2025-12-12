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
