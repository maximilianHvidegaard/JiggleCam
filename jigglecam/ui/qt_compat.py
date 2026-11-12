"""Pick the Qt binding that picamera2's preview widgets were built against.

Why this exists: picamera2's Qt preview widgets (QGlPicamera2 / QPicamera2)
import a specific PyQt binding internally. Historically that is PyQt5; newer
picamera2 versions may use PyQt6. Mixing bindings in one process breaks
(two QApplications, widgets that can't be parented), so the rest of the app
must use *whatever binding picamera2 chose*. We detect it once here and every
other module imports Qt via this file:

    from jigglecam.ui.qt_compat import QtCore, QtGui, QtWidgets, Qt

If picamera2 is not installed (e.g. running check_touch.py on a desktop),
we fall back to PyQt6, then PyQt5, and the preview widgets are None.

All enum access in this project uses the fully scoped form
(Qt.AlignmentFlag.AlignCenter), which works in both PyQt5 and PyQt6.
"""

from __future__ import annotations

import importlib
from types import ModuleType

QGlPicamera2 = None
QPicamera2 = None
PREVIEW_IMPORT_ERROR: str | None = None
BINDING: str | None = None


def _binding_of(cls: type) -> str | None:
    for base in cls.__mro__:
        mod = getattr(base, "__module__", "") or ""
        if mod.startswith(("PyQt5", "PyQt6")):
            return mod.split(".")[0]
    return None


try:
    from picamera2.previews.qt import QGlPicamera2, QPicamera2  # type: ignore[no-redef]

    BINDING = _binding_of(QPicamera2) or _binding_of(QGlPicamera2)
except Exception as exc:  # ImportError, or OpenGL/EGL failures inside picamera2
    PREVIEW_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    QGlPicamera2 = QPicamera2 = None

if BINDING is None:
    for candidate in ("PyQt6", "PyQt5"):
        try:
            importlib.import_module(f"{candidate}.QtWidgets")
            BINDING = candidate
            break
        except ImportError:
            continue

if BINDING is None:
    raise ImportError(
        "No usable Qt binding found. On the Pi run scripts/setup_pi.sh "
        "(installs python3-pyqt5 / python3-pyqt6 from apt)."
    )

QtCore: ModuleType = importlib.import_module(f"{BINDING}.QtCore")
QtGui: ModuleType = importlib.import_module(f"{BINDING}.QtGui")
QtWidgets: ModuleType = importlib.import_module(f"{BINDING}.QtWidgets")
Qt = QtCore.Qt

# QShortcut moved from QtWidgets (Qt5) to QtGui (Qt6).
QShortcut = getattr(QtGui, "QShortcut", None) or getattr(QtWidgets, "QShortcut")


def summary() -> str:
    """One-line description for logs and the status bar."""
    preview = "preview widgets OK" if QGlPicamera2 is not None else f"no preview widgets ({PREVIEW_IMPORT_ERROR})"
    return f"{BINDING} (Qt {QtCore.QT_VERSION_STR}), {preview}"
