"""Choose one Qt binding for the whole app and load picamera2's preview widgets for it.

Every module imports Qt via this file:

    from jigglecam.ui.qt_compat import QtCore, QtGui, QtWidgets, Qt

Why this exists: mixing Qt bindings in one process breaks (two QApplications,
widgets that can't be parented). Current picamera2 supports PyQt5, PyQt6 and
PySide, and loads its preview widgets *lazily* via a module __getattr__ for
whichever binding it is told to use. So we pick the binding ourselves (PyQt6,
else PyQt5), tell picamera2 to use the same one, and ask for each widget
separately. A broken GL widget must not take the CPU widget down with it.

What we learned from picamera2's source (Nov 2026): its OpenGL widgets need an
X11 or Wayland display server. If their OpenGL imports fail, picamera2 logs
"OpenGL will not be available" and touching QGlPicamera2 raises
NameError: _get_qglpicamera2. On Pi OS Lite (eglfs, no display server) the GL
widget cannot work at all; only the CPU widget (QPicamera2) can.

All enum access in this project uses the fully scoped form
(Qt.AlignmentFlag.AlignCenter), which works in both PyQt5 and PyQt6.
"""

from __future__ import annotations

import importlib
import os
from types import ModuleType

PREFERRED_BINDINGS = ("PyQt6", "PyQt5")

BINDING: str | None = None
for _candidate in PREFERRED_BINDINGS:
    try:
        importlib.import_module(f"{_candidate}.QtWidgets")
        BINDING = _candidate
        break
    except ImportError:
        continue
if BINDING is None:
    raise ImportError(
        "No usable Qt binding found. On the Pi run scripts/setup_pi.sh "
        "(installs python3-pyqt6 / python3-pyqt5 from apt)."
    )

QtCore: ModuleType = importlib.import_module(f"{BINDING}.QtCore")
QtGui: ModuleType = importlib.import_module(f"{BINDING}.QtGui")
QtWidgets: ModuleType = importlib.import_module(f"{BINDING}.QtWidgets")
Qt = QtCore.Qt

# QShortcut moved from QtWidgets (Qt5) to QtGui (Qt6).
QShortcut = getattr(QtGui, "QShortcut", None) or getattr(QtWidgets, "QShortcut")

# Tell picamera2 which binding to use before it resolves any widget.
os.environ.setdefault("PICAMERA2_QT_BINDING", BINDING)

_SUFFIX = {"PyQt5": "5", "PyQt6": "6"}[BINDING]
_widget_cache: dict[str, type] = {}
_widget_errors: dict[str, str] = {}


def _binding_of(cls: type) -> str | None:
    for base in cls.__mro__:
        mod = getattr(base, "__module__", "") or ""
        if mod.startswith(("PyQt5", "PyQt6")):
            return mod.split(".")[0]
    return None


def _load_widget(kind: str):
    """kind = "software" (QPicamera2) or "gl" (QGlPicamera2). Returns class/factory or None."""
    if kind in _widget_cache:
        return _widget_cache[kind]
    if kind in _widget_errors:
        return None
    base = "QPicamera2" if kind == "software" else "QGlPicamera2"
    # Explicit per-binding names in current picamera2: Q6Picamera2 / QGl6Picamera2.
    explicit = ("Q" if kind == "software" else "QGl") + _SUFFIX + "Picamera2"
    try:
        qt_mod = importlib.import_module("picamera2.previews.qt")
        try:
            from picamera2 import Picamera2

            if getattr(Picamera2, "qt_binding", None) is None and hasattr(Picamera2, "qt_binding"):
                Picamera2.qt_binding = BINDING
        except Exception:
            pass
        widget = None
        for name in (explicit, base):  # older picamera2 only has the generic name
            try:
                widget = getattr(qt_mod, name)
                break
            except AttributeError:
                continue
        if widget is None:
            raise AttributeError(f"picamera2.previews.qt has neither {explicit} nor {base}")
        if isinstance(widget, type):
            got = _binding_of(widget)
            if got and got != BINDING:
                raise ImportError(f"picamera2 gave a {got} widget but the app uses {BINDING}")
    except Exception as exc:  # NameError from broken OpenGL imports lands here too
        _widget_errors[kind] = f"{type(exc).__name__}: {exc}"
        return None
    _widget_cache[kind] = widget
    return widget


def preview_widget(kind: str):
    """Return picamera2's preview widget class for `kind`, or None if unavailable."""
    return _load_widget(kind)


def preview_error(kind: str) -> str | None:
    _load_widget(kind)
    return _widget_errors.get(kind)


def summary() -> str:
    """One-line description for logs and the status bar."""
    parts = [f"{BINDING} (Qt {QtCore.QT_VERSION_STR})"]
    for kind in ("software", "gl"):
        err = preview_error(kind)
        parts.append(f"{kind} preview: {'OK' if err is None else 'unavailable (' + err + ')'}")
    return ", ".join(parts)
