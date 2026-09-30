"""Context manager tests. They write only inside pytest's temporary folder."""

import pytest

from app.files import AtomicFileWriter


def test_writes_the_file_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "out.txt"

    with AtomicFileWriter(target) as f:
        f.write("hello")

    assert target.read_text() == "hello"
    assert list(tmp_path.iterdir()) == [target]


def test_error_inside_block_closes_and_deletes_temp_file(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old content")

    with pytest.raises(RuntimeError):
        with AtomicFileWriter(target) as f:
            handle = f
            f.write("new content, half writ")
            raise RuntimeError("crash in the middle of writing")

    assert handle.closed                                   # the file was closed
    assert target.read_text() == "old content"             # the target was not touched
    assert list(tmp_path.iterdir()) == [target]            # the temp file is gone


def test_error_when_target_did_not_exist_creates_nothing(tmp_path):
    target = tmp_path / "new.txt"

    with pytest.raises(KeyError):
        with AtomicFileWriter(target):
            raise KeyError("oops")

    assert list(tmp_path.iterdir()) == []


def test_creates_missing_folders(tmp_path):
    target = tmp_path / "a" / "b" / "out.txt"

    with AtomicFileWriter(target) as f:
        f.write("x")

    assert target.read_text() == "x"


def test_binary_mode(tmp_path):
    target = tmp_path / "out.bin"

    with AtomicFileWriter(target, mode="wb") as f:
        f.write(b"\x00\x01")

    assert target.read_bytes() == b"\x00\x01"
