"""App entry point:  python -m ckapp [clip or folder ...]"""
from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")


def _excepthook(kind, value, tb) -> None:
    """Log crashes to the state folder; the windowed (pythonw) build has no console."""
    from ..config import state_dir
    text = "".join(traceback.format_exception(kind, value, tb))
    try:
        with open(state_dir() / "crash.log", "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    sys.__excepthook__(kind, value, tb)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    sys.excepthook = _excepthook
    from PySide6.QtGui import QIcon, QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    from .. import APP_ID, APP_NAME
    from . import theme as T
    from .viewer import default_surface_format

    QSurfaceFormat.setDefaultFormat(default_surface_format())     # must precede QApplication
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(T.ASSETS / "app.ico")))
    T.apply(app)

    from .main_window import MainWindow
    win = MainWindow()
    win.show()
    win.client.connect_engine()
    if argv:
        win.import_paths(argv)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
