import json
from pathlib import Path

import pytest

from decman.core.store import Store


def test_store_initially_empty_when_file_missing(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    assert not path.exists()

    store = Store(path)

    assert store.get("missing") is None
    with pytest.raises(KeyError):
        _ = store["missing"]


def test_store_loads_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    original = {"foo": "bar", "number": 123}
    path.write_text(json.dumps(original), encoding="utf-8")

    store = Store(path)

    assert store["foo"] == "bar"
    assert store["number"] == 123
    # underlying representation is dict-like
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_setitem_and_getitem_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "store.json"

    store = Store(path)
    store["foo"] = "bar"
    store["number"] = 123

    assert store["foo"] == "bar"
    assert store["number"] == 123


def test_get_with_default(tmp_path: Path) -> None:
    path = tmp_path / "store.json"

    store = Store(path)
    store["present"] = "value"

    assert store.get("present") == "value"
    assert store.get("missing") is None
    assert store.get("missing", "default") == "default"


def test_save_creates_parent_directory_and_persists(tmp_path: Path) -> None:
    # use nested directory to ensure parent creation is exercised
    path = tmp_path / "nested" / "store.json"

    store = Store(path)
    store["foo"] = "bar"

    store.save()

    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"foo": "bar"}


def test_context_manager_saves_on_normal_exit(tmp_path: Path) -> None:
    path = tmp_path / "store.json"

    with Store(path) as store:
        store["foo"] = "bar"
        store["number"] = 123

    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"foo": "bar", "number": 123}


def test_context_manager_saves_even_on_exception(tmp_path: Path) -> None:
    path = tmp_path / "store.json"

    with pytest.raises(RuntimeError):
        with Store(path) as store:
            store["foo"] = "bar"
            raise RuntimeError("boom")

    # file should still be written despite the exception
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"foo": "bar"}


def test_repr_matches_underlying_dict(tmp_path: Path) -> None:
    path = tmp_path / "store.json"

    store = Store(path)
    store["foo"] = "bar"
    store["number"] = 123

    expected = repr({"foo": "bar", "number": 123})
    assert repr(store) == expected
