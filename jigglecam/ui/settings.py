"""Settings screen. For now it only *shows* information (owner decision):
nothing here is editable yet, so no settings file format is needed yet.
Editable settings arrive once the save format is decided (see CLAUDE.md).
"""

from __future__ import annotations

import shutil

from jigglecam import __version__, config
from jigglecam.capture import CaptureSource
from jigglecam.config import Config
from jigglecam.storage import SetStore
from jigglecam.ui import qt_compat
from jigglecam.ui.qt_compat import Qt, QtCore, QtWidgets
from jigglecam.ui.widgets import BG, enable_touch_scroll, top_bar


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def gather_info(cfg: Config, source: CaptureSource, store: SetStore, preview_backend: str,
                platform: str, screen: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Sections of (label, value) rows. Pure apart from reading the disk."""
    count, used = store.usage()
    root = store.root
    probe = root if root.exists() else root.parent
    try:
        disk = shutil.disk_usage(probe)
        free = f"{human_bytes(disk.free)} of {human_bytes(disk.total)}"
    except OSError:
        free = "unknown"
    cfg_files = [p.name for p in (config.DEFAULT_PATH, config.LOCAL_PATH) if p.exists()]
    return [
        ("Camera", list(source.info().items())),
        ("Storage", [
            ("Folder", str(root)),
            ("Shots", str(count)),
            ("Space used", human_bytes(used)),
            ("Free on card", free),
            ("JPEG quality", str(cfg.storage.jpeg_quality)),
        ]),
        ("Display", [
            ("Screen", screen),
            ("Qt", f"{qt_compat.BINDING} (Qt {QtCore.QT_VERSION_STR}), platform {platform}"),
            ("Viewfinder", f"{preview_backend} preview, {cfg.preview.width}x{cfg.preview.height}"),
        ]),
        ("App", [
            ("Version", __version__),
            ("Config files", ", ".join(cfg_files) or "none"),
            ("Playback speed", f"{cfg.ui.playback_frame_ms} ms per frame"),
        ]),
    ]


class SettingsScreen(QtWidgets.QWidget):
    back = QtCore.pyqtSignal()

    def __init__(self, info_fn):
        """info_fn() -> sections, called each time the screen opens (storage changes)."""
        super().__init__()
        self._info_fn = info_fn
        self.setStyleSheet(f"background: {BG}; color: #ddd;")
        bar, back_btn, _, _ = top_bar("‹  Camera", "Settings")
        back_btn.clicked.connect(self.back.emit)
        hint = QtWidgets.QLabel("read-only for now")
        hint.setStyleSheet("color: #666; font-size: 12px; padding-right: 8px;")
        bar.layout().addWidget(hint)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; }")
        enable_touch_scroll(self.scroll)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        host = QtWidgets.QWidget()
        form = QtWidgets.QGridLayout(host)
        form.setContentsMargins(20, 10, 20, 20)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(8)
        row = 0
        for section, rows in self._info_fn():
            head = QtWidgets.QLabel(section)
            head.setStyleSheet("color: #8ab4f8; font-size: 15px; padding-top: 10px;")
            form.addWidget(head, row, 0, 1, 2)
            row += 1
            for label, value in rows:
                k = QtWidgets.QLabel(label)
                k.setStyleSheet("color: #888; font-size: 14px;")
                v = QtWidgets.QLabel(value)
                v.setStyleSheet("font-size: 14px;")
                v.setWordWrap(True)
                form.addWidget(k, row, 0, Qt.AlignmentFlag.AlignTop)
                form.addWidget(v, row, 1)
                row += 1
        form.setColumnStretch(1, 1)
        form.setRowStretch(row, 1)
        self.scroll.setWidget(host)
