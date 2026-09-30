"""Custom context manager for writing files safely."""

import os
import tempfile
from pathlib import Path


class AtomicFileWriter:
    """Write a file so that it ends up either fully written or not changed at all.

    Usage:
        with AtomicFileWriter("data/result.json") as f:
            f.write("...")

    On entry it opens a temporary file in the same folder and gives it to the
    `with` block. On a normal exit it closes the temporary file and moves it
    over the target. If the block raises, it closes and deletes the temporary
    file, leaves the target as it was, and lets the error continue.
    """

    def __init__(self, path: str | Path, mode: str = "w", encoding: str = "utf-8"):
        self.path = Path(path)
        self.mode = mode
        self.encoding = None if "b" in mode else encoding
        self._file = None
        self._tmp_path = None

    # AI-assisted: drafted with an AI assistant for this reference solution.
    # In your own project, say here what Copilot suggested and what you changed or checked.
    # Pattern: the __enter__/__exit__ pair of a context manager class.
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The temporary file is created next to the target, so the final move stays on one drive.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        self._tmp_path = Path(tmp)
        self._file = os.fdopen(fd, self.mode, encoding=self.encoding)
        print(f"[file] opened {self._tmp_path.name} for {self.path}", flush=True)
        return self._file

    def __exit__(self, exc_type, exc_value, traceback):
        # Runs however the block ends: normally, by return, or by an exception.
        self._file.close()
        if exc_type is None:
            os.chmod(self._tmp_path, 0o644)  # mkstemp makes the file private to the owner; use normal permissions
            os.replace(self._tmp_path, self.path)  # replaces the target in one step
            print(f"[file] saved {self.path}", flush=True)
        else:
            self._tmp_path.unlink(missing_ok=True)
            print(f"[file] {exc_type.__name__} inside the with block: closed and deleted "
                  f"{self._tmp_path.name}, {self.path} was not changed", flush=True)
        return False  # False means: do not swallow the exception, let it continue
