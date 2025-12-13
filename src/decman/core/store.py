import json
import os
import pathlib
import tempfile
import typing


class Store:
    """
    Key-value store for saving decman state.
    """

    def __init__(self, path: str, dry_run: bool = False) -> None:
        self._store: dict[str, typing.Any] = {}
        self._path = pathlib.Path(path)
        self._dry_run = dry_run

        if self._path.exists():
            with self._path.open("rt", encoding="utf-8") as file:
                self._store = json.load(file, object_hook=_decode_sets)

    def __getitem__(self, key: str) -> typing.Any:
        return self._store[key]

    def __setitem__(self, key: str, value: typing.Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        return self._store.get(key, default)

    def ensure(self, key: str, default: typing.Any = None):
        if key not in self._store:
            self._store[key] = default

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, exc_type, exc, tb):
        self.save()
        return False

    def save(self) -> None:
        """
        Saves the store to the defined path.
        """
        if self._dry_run:
            return

        os.makedirs(self._path.parent, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            "wt",
            encoding="utf-8",
            dir=self._path.parent,
            delete=False,
        ) as tmp:
            json.dump(self._store, tmp, cls=_SetJSONEncoder, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())

        os.replace(tmp.name, self._path)

    def __repr__(self) -> str:
        return repr(self._store)


class _SetJSONEncoder(json.JSONEncoder):
    def default(self, obj: typing.Any) -> typing.Any:
        if isinstance(obj, set):
            # generic, works for any set value
            return {"__type__": "set", "items": list(obj)}
        return super().default(obj)


def _decode_sets(obj: typing.Any) -> typing.Any:
    if isinstance(obj, dict) and obj.get("__type__") == "set" and "items" in obj:
        return set(obj["items"])
    return obj
