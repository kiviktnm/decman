import os
import stat
from pathlib import Path

# Adjust this import to match your actual module location
import decman.core.fs as fs

# --- fs.File tests --------------------------------------------------------------


def test_file_from_content_creates_and_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"

    f = fs.File(content="hello", permissions=0o600)

    # First run: file must be created and reported as changed
    changed1 = f.copy_to(str(target))
    assert changed1 is True
    assert target.read_text(encoding="utf-8") == "hello"

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600

    # Second run with same configuration: no content change
    changed2 = f.copy_to(str(target))
    assert changed2 is False
    assert target.read_text(encoding="utf-8") == "hello"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_file_content_with_variables_and_change_detection(tmp_path: Path) -> None:
    target = tmp_path / "templated.txt"

    f = fs.File(content="hello {{NAME}}")

    # First run: NAME=world
    changed1 = f.copy_to(str(target), {"{{NAME}}": "world"})
    assert changed1 is True
    assert target.read_text(encoding="utf-8") == "hello world"

    # Second run: same variables, no change
    changed2 = f.copy_to(str(target), {"{{NAME}}": "world"})
    assert changed2 is False
    assert target.read_text(encoding="utf-8") == "hello world"

    # Third run: different variables, should change
    changed3 = f.copy_to(str(target), {"{{NAME}}": "there"})
    assert changed3 is True
    assert target.read_text(encoding="utf-8") == "hello there"


def test_file_from_source_text_with_and_without_variables(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text("VALUE={{X}}", encoding="utf-8")
    target = tmp_path / "dst.txt"

    # Without variables (raw copy)
    f_raw = fs.File(source_file=str(src))
    changed1 = f_raw.copy_to(str(target), {})
    assert changed1 is True
    assert target.read_text(encoding="utf-8") == "VALUE={{X}}"

    # Idempotent raw copy
    changed2 = f_raw.copy_to(str(target), {})
    assert changed2 is False

    # With variables (substitution)
    f_sub = fs.File(source_file=str(src))
    changed3 = f_sub.copy_to(str(target), {"{{X}}": "42"})
    assert changed3 is True
    assert target.read_text(encoding="utf-8") == "VALUE=42"

    # Idempotent after substitution
    changed4 = f_sub.copy_to(str(target), {"{{X}}": "42"})
    assert changed4 is False


def test_file_binary_from_content(tmp_path: Path) -> None:
    target = tmp_path / "bin.dat"
    payload = b"\x00\x01\x02hello"

    f = fs.File(content=payload.decode("latin1"), bin_file=True)

    changed1 = f.copy_to(str(target))
    assert changed1 is True
    assert target.read_bytes() == payload

    # Idempotent: second call does not rewrite
    changed2 = f.copy_to(str(target))
    assert changed2 is False
    assert target.read_bytes() == payload


def test_file_binary_copy_from_source(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    payload = b"\x10\x20\x30binary"
    src.write_bytes(payload)
    target = tmp_path / "dst.bin"

    f = fs.File(source_file=str(src), bin_file=True)

    changed1 = f.copy_to(str(target), {"IGNORED": "x"})
    assert changed1 is True
    assert target.read_bytes() == payload

    # Idempotent, comparing bytes
    changed2 = f.copy_to(str(target), {"IGNORED": "x"})
    assert changed2 is False
    assert target.read_bytes() == payload


def test_file_creates_parent_directories_and_applies_permissions(tmp_path: Path) -> None:
    nested_dir = tmp_path / "a" / "b" / "c"
    target = nested_dir / "file.txt"

    f = fs.File(content="data", permissions=0o644)

    changed = f.copy_to(str(target))
    assert changed is True
    assert target.read_text(encoding="utf-8") == "data"

    # Directories created
    assert nested_dir.is_dir()

    # Permissions on file
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o644


# --- fs.Directory tests ---------------------------------------------------------


def _create_sample_source_tree(root: Path) -> None:
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("A={{X}}", encoding="utf-8")
    (root / "sub" / "b.txt").write_text("B={{X}}", encoding="utf-8")


def test_directory_copy_to_creates_and_is_idempotent(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()

    _create_sample_source_tree(src_dir)

    d = fs.Directory(
        source_directory=str(src_dir),
        bin_files=False,
        encoding="utf-8",
        permissions=0o644,
    )

    # First run: both fs should be created and reported as changed
    changed1 = d.copy_to(str(dst_dir), variables={"{{X}}": "1"})
    expected_paths = {
        str(dst_dir / "a.txt"),
        str(dst_dir / "sub" / "b.txt"),
    }
    assert set(changed1) == expected_paths

    assert (dst_dir / "a.txt").read_text(encoding="utf-8") == "A=1"
    assert (dst_dir / "sub" / "b.txt").read_text(encoding="utf-8") == "B=1"

    # Second run with same variables: no fs should be reported as changed
    changed2 = d.copy_to(str(dst_dir), variables={"{{X}}": "1"})
    assert changed2 == []


def test_directory_copy_to_detects_changes_via_variables(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    _create_sample_source_tree(src_dir)

    d = fs.Directory(source_directory=str(src_dir))

    # Initial materialization
    changed1 = d.copy_to(str(dst_dir), variables={"{{X}}": "alpha"})
    assert set(changed1) == {
        str(dst_dir / "a.txt"),
        str(dst_dir / "sub" / "b.txt"),
    }

    # Change variables -> both fs change
    changed2 = d.copy_to(str(dst_dir), variables={"{{X}}": "beta"})
    assert set(changed2) == {
        str(dst_dir / "a.txt"),
        str(dst_dir / "sub" / "b.txt"),
    }

    assert (dst_dir / "a.txt").read_text(encoding="utf-8") == "A=beta"
    assert (dst_dir / "sub" / "b.txt").read_text(encoding="utf-8") == "B=beta"


def test_directory_copy_to_dry_run(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    _create_sample_source_tree(src_dir)

    d = fs.Directory(source_directory=str(src_dir))

    # First, actually materialize once
    d.copy_to(str(dst_dir), variables={"{{X}}": "1"})

    # Now perform dry-run with different variables; contents must not change
    before_a = (dst_dir / "a.txt").read_text(encoding="utf-8")
    before_b = (dst_dir / "sub" / "b.txt").read_text(encoding="utf-8")

    changed_dry = d.copy_to(
        str(dst_dir),
        variables={"{{X}}": "2"},
        dry_run=True,
    )

    expected_paths = {
        str(dst_dir / "a.txt"),
        str(dst_dir / "sub" / "b.txt"),
    }
    assert set(changed_dry) == expected_paths

    # Contents remain as before (no writes in dry-run)
    assert (dst_dir / "a.txt").read_text(encoding="utf-8") == before_a
    assert (dst_dir / "sub" / "b.txt").read_text(encoding="utf-8") == before_b


def test_directory_copy_to_restores_working_directory(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    _create_sample_source_tree(src_dir)

    d = fs.Directory(source_directory=str(src_dir))

    original_cwd = os.getcwd()
    try:
        changed = d.copy_to(str(dst_dir), variables={"{{X}}": "x"})
        assert set(changed) == {
            str(dst_dir / "a.txt"),
            str(dst_dir / "sub" / "b.txt"),
        }
    finally:
        # Ensure the implementation restored CWD
        assert os.getcwd() == original_cwd
