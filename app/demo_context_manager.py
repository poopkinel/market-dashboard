"""Shows what AtomicFileWriter does when the code inside the `with` block fails.

Run from the project folder:
    python -m app.demo_context_manager

The second `with` block raises an error that nothing handles, so the script
ends with a traceback. The [file] lines printed before it show that the
context manager still closed and deleted the temporary file.
"""

from pathlib import Path

from app.files import AtomicFileWriter

PATH = Path("data") / "demo.txt"


def main() -> None:
    with AtomicFileWriter(PATH) as f:
        f.write("first version\n")
    print("File contains:", PATH.read_text().strip())

    try:
        with AtomicFileWriter(PATH) as f:
            f.write("second version, half writ")
            raise RuntimeError("simulated crash while writing")  # not handled anywhere
    finally:
        # Runs even though the error is not handled. The traceback comes after these lines.
        print("File object closed:", f.closed)
        print("File still contains:", PATH.read_text().strip())


if __name__ == "__main__":
    main()
