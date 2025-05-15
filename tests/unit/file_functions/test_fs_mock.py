import os
import stat
import pytest
from pathlib import Path


# Helper to test both str and Path inputs
@pytest.fixture(params=[lambda p: p, lambda p: str(p)])
def as_pathlike(request):
    return request.param


def test_stat_and_lstat_file(tmp_path, as_pathlike, real_fs):
    f = tmp_path / "file.txt"
    content = b"hello"
    f.write_bytes(content)

    # stat
    res1 = real_fs.stat(as_pathlike(f))
    assert isinstance(res1, os.stat_result)
    assert res1.st_size == len(content)

    # lstat on regular file
    res2 = real_fs.lstat(as_pathlike(f))
    assert isinstance(res2, os.stat_result)
    assert stat.S_ISREG(res2.st_mode)


def test_lstat_symlink(tmp_path, as_pathlike, real_fs):
    target = tmp_path / "tgt.txt"
    target.write_text("x")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    res = real_fs.lstat(as_pathlike(link))
    # lstat should report a symlink bit
    assert stat.S_ISLNK(res.st_mode)


def test_stat_not_found(tmp_path, as_pathlike, real_fs):
    with pytest.raises(FileNotFoundError):
        real_fs.stat(as_pathlike(tmp_path / "nope.txt"))
    with pytest.raises(FileNotFoundError):
        real_fs.lstat(as_pathlike(tmp_path / "nope.txt"))


def test_exists(tmp_path, as_pathlike, real_fs):
    f = tmp_path / "e.txt"
    d = tmp_path / "d"
    f.write_text("x")
    d.mkdir()

    assert real_fs.exists(as_pathlike(f)) is True
    assert real_fs.exists(as_pathlike(d)) is True
    assert real_fs.exists(as_pathlike(tmp_path / "none")) is False


def test_open_binary_and_text(tmp_path: Path, as_pathlike, real_fs):
    f = tmp_path / "b.bin"
    data = b"\x00\x01"
    # binary write/read - no encoding parameter needed or desired
    with real_fs.open(as_pathlike(f), "wb") as w:
        n = w.write(data)
        assert n == len(data)
    with real_fs.open(as_pathlike(f), "rb") as r:
        assert r.read() == data

    # text write/read with explicit UTF-8
    t = tmp_path / "t.txt"
    text_content = "hello, world! café €"  # Using some non-ASCII characters

    # Write with explicit UTF-8 encoding
    with real_fs.open(as_pathlike(t), "w", encoding="utf-8") as w_text:
        w_text.write(text_content)

    # Read with explicit UTF-8 encoding
    with real_fs.open(as_pathlike(t), "r", encoding="utf-8") as r_text:
        assert r_text.read() == text_content

    t_default_encoding = tmp_path / "t_default_encoding.txt"
    simple_text = "default encoding test"
    with real_fs.open(as_pathlike(t_default_encoding), "w") as w_default:
        w_default.write(simple_text)
    with real_fs.open(as_pathlike(t_default_encoding), "r") as r_default:
        assert r_default.read() == simple_text


def test_listdir_and_errors(tmp_path, as_pathlike, real_fs):
    d = tmp_path / "lst"
    d.mkdir()
    (d / "a.txt").touch()
    (d / "b").mkdir()

    out = real_fs.listdir(as_pathlike(d))
    assert isinstance(out, list)
    assert set(out) == {"a.txt", "b"}

    # not a dir
    f = tmp_path / "f.txt"
    f.touch()
    with pytest.raises(NotADirectoryError):
        real_fs.listdir(as_pathlike(f))
    # not found
    with pytest.raises(FileNotFoundError):
        real_fs.listdir(as_pathlike(tmp_path / "nope"))


def test_path_abspath_and_is_dir(tmp_path, as_pathlike, real_fs):
    d = tmp_path / "sub/dir"
    # abspath doesn't require existence
    out = real_fs.path_abspath(as_pathlike(d))
    assert isinstance(out, str)
    assert os.path.isabs(out)

    # is_dir
    d.mkdir(parents=True)
    assert real_fs.is_dir(as_pathlike(d)) is True
    assert real_fs.is_dir(as_pathlike(tmp_path / "nope")) is False


def test_mkdir(tmp_path, as_pathlike, real_fs):
    new = tmp_path / "x/y/z"
    real_fs.mkdir(as_pathlike(new))  # exist_ok=True default
    assert new.is_dir()

    # exist_ok=False on existing dir raises
    with pytest.raises(FileExistsError):
        real_fs.mkdir(as_pathlike(tmp_path), exist_ok=False)


def test_resolve_strict_and_non_strict(tmp_path, as_pathlike, real_fs):
    p = tmp_path / "foo/bar.txt"
    p.parent.mkdir(parents=True)
    p.write_text("x")

    # strict=True works for existing
    out1 = real_fs.resolve(as_pathlike(p), strict=True)
    assert isinstance(out1, Path)
    assert out1 == p.resolve()

    # strict=True on missing raises
    missing = tmp_path / "no" / "file"
    with pytest.raises(FileNotFoundError):
        real_fs.resolve(as_pathlike(missing), strict=True)

    # strict=False returns absolute
    out2 = real_fs.resolve(as_pathlike(missing), strict=False)
    assert isinstance(out2, Path)
    assert out2.is_absolute()
    assert out2 == Path(missing).absolute()  # More specific check


def test_access(tmp_path, as_pathlike, real_fs):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert real_fs.access(as_pathlike(f), os.F_OK) is True
    # unlikely to be executable
    assert real_fs.access(as_pathlike(f), os.X_OK) in (True, False)
    # non-existent
    assert real_fs.access(as_pathlike(tmp_path / "no"), os.F_OK) is False


def test_move_overwrite_and_errors(tmp_path, as_pathlike, real_fs):
    src = tmp_path / "src.txt"
    src.write_text("1")
    dst = tmp_path / "dst.txt"
    dst.write_text("old")
    # overwrite
    real_fs.move(as_pathlike(src), as_pathlike(dst))
    assert not src.exists()
    assert dst.read_text() == "1"

    # move into dir
    src2 = tmp_path / "s2.txt"
    src2.write_text("2")
    d = tmp_path / "dir"
    d.mkdir()
    real_fs.move(as_pathlike(src2), as_pathlike(d))
    assert (d / "s2.txt").read_text() == "2"

    # missing src
    missing_src = tmp_path / "no_such_file.txt"
    with pytest.raises(
        FileNotFoundError
    ):  # More specific if this is the expected error
        real_fs.move(as_pathlike(missing_src), as_pathlike(d))


def test_is_file_and_scandir(tmp_path, as_pathlike, real_fs):
    f = tmp_path / "f.txt"
    f.write_text("x")
    d = tmp_path / "d"
    d.mkdir()
    link = tmp_path / "ln"
    link.symlink_to(f)

    # is_file
    assert real_fs.is_file(as_pathlike(f)) is True
    assert real_fs.is_file(as_pathlike(d)) is False
    # symlink follows
    assert real_fs.is_file(as_pathlike(link)) is True

    # scandir success
    names = set()
    with real_fs.scandir(as_pathlike(tmp_path)) as it:
        for entry in it:
            names.add(entry.name)
    assert {"f.txt", "d", "ln"} <= names

    # scandir errors
    with pytest.raises(FileNotFoundError):
        with real_fs.scandir(as_pathlike(tmp_path / "no")):
            pass
    with pytest.raises(NotADirectoryError):
        dummy = tmp_path / "file"
        dummy.write_text("x")
        with real_fs.scandir(as_pathlike(dummy)):
            pass


def test_relative_to(tmp_path, as_pathlike, real_fs):
    base = tmp_path / "base"
    (base / "x").mkdir(parents=True)
    file = base / "x" / "f.txt"
    file.write_text("x")

    rel = real_fs.relative_to(as_pathlike(file), as_pathlike(base))
    assert isinstance(rel, Path)
    assert str(rel) == os.path.join("x", "f.txt")

    # same path
    rel2 = real_fs.relative_to(as_pathlike(base), as_pathlike(base))
    assert str(rel2) == "."

    # not related
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError):
        real_fs.relative_to(as_pathlike(file), as_pathlike(other))
