"""On-disk format for capture sets (owner decision: folder of JPEGs + JSON).

    <storage.root>/
      2026-11-12_14-03-22/
        frame_1.jpg ... frame_N.jpg   views left to right, full capture size
        thumb.jpg                      small preview of frame_1 for the UI
        set.json                       metadata, see below

set.json (format_version 1):
    {
      "format_version": 1,
      "captured_at": "2026-11-12T14:03:22.123456",
      "source": "single_camera_burst",
      "views": 4,
      "size": [2304, 1296],
      "lock": {"exposure_time_us": ..., "analogue_gain": ..., "colour_gains": [r, b],
               "lens_position": ... | null},
      "lock_verified": true,
      "spread_ms": 100.1,               # first-to-last frame time
      "frames": [{"file": "frame_1.jpg", "view_index": 0, "camera_index": 0,
                  "sensor_timestamp_ns": ..., "exposure_time_us": ..., ...}, ...],
      "extra": {...}                    # source-specific notes
    }

Phase 3 adds processing results (subject point, offsets, GIF/MP4) to the
same folder. Writes are atomic: everything goes into a hidden ".tmp-" folder
that is renamed into place only when complete, so a crash or power loss
never leaves a half-written set that the gallery would try to show.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from jigglecam.capture.base import FrameSet
from jigglecam.config import StorageConfig

FORMAT_VERSION = 1
NAME_FORMAT = "%Y-%m-%d_%H-%M-%S"


@dataclass(frozen=True)
class StoredSet:
    path: Path
    meta: dict

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def frame_paths(self) -> list[Path]:
        return [self.path / f["file"] for f in self.meta["frames"]]

    @property
    def thumb_path(self) -> Path:
        return self.path / "thumb.jpg"


class SetStore:
    def __init__(self, cfg: StorageConfig):
        self.cfg = cfg
        self.root = cfg.root_path

    def _unique_dir(self, base: str) -> Path:
        candidate, n = self.root / base, 2
        while candidate.exists():
            candidate = self.root / f"{base}_{n}"
            n += 1
        return candidate

    def save(self, fs: FrameSet) -> StoredSet:
        from PIL import Image  # python3-pil from apt (a picamera2 dependency)

        self.root.mkdir(parents=True, exist_ok=True)
        final = self._unique_dir(fs.captured_at.strftime(NAME_FORMAT))
        tmp = self.root / f".tmp-{final.name}"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir()
        try:
            frames_meta = []
            for i, frame in enumerate(fs.frames, start=1):
                fname = f"frame_{i}.jpg"
                img = Image.fromarray(frame.image)
                img.save(tmp / fname, quality=self.cfg.jpeg_quality)
                frames_meta.append({"file": fname, **asdict(frame.meta)})
                if i == 1:
                    thumb = img.copy()
                    w = self.cfg.thumb_width
                    thumb.thumbnail((w, w * img.height // max(img.width, 1)))
                    thumb.save(tmp / "thumb.jpg", quality=85)
            h, w = fs.frames[0].image.shape[:2]
            meta = {
                "format_version": FORMAT_VERSION,
                "captured_at": fs.captured_at.isoformat(),
                "source": fs.source,
                "views": len(fs.frames),
                "size": [w, h],
                "lock": asdict(fs.lock),
                "lock_verified": fs.lock_verified,
                "spread_ms": round(fs.spread_ms, 3),
                "frames": frames_meta,
                "extra": fs.extra,
            }
            (tmp / "set.json").write_text(json.dumps(meta, indent=2))
            tmp.rename(final)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return StoredSet(path=final, meta=meta)

    def load(self, path: Path) -> StoredSet:
        meta = json.loads((path / "set.json").read_text())
        if meta.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"{path}: unsupported format_version {meta.get('format_version')}")
        return StoredSet(path=path, meta=meta)

    def list(self) -> list[StoredSet]:
        """All complete sets, newest first. Unreadable folders are skipped."""
        if not self.root.exists():
            return []
        out = []
        for d in sorted(self.root.iterdir(), reverse=True):
            if d.is_dir() and not d.name.startswith(".") and (d / "set.json").exists():
                try:
                    out.append(self.load(d))
                except (ValueError, OSError, json.JSONDecodeError):
                    continue
        return out

    def latest(self) -> StoredSet | None:
        sets = self.list()
        return sets[0] if sets else None

    def delete(self, stored: StoredSet) -> None:
        """Remove a set from disk. Permanent: there is no trash.

        The folder is first renamed to a hidden ".trash-" name, so list() stops
        showing it at once and a crash halfway through never leaves a set with
        missing frames. Leftover .trash- folders are cleaned up on the next delete.
        """
        path = stored.path.resolve()
        if path.parent != self.root.resolve() or path.name.startswith("."):
            raise ValueError(f"refusing to delete {path}: not a set in {self.root}")
        trash = self.root / f".trash-{path.name}"
        if trash.exists():
            shutil.rmtree(trash)
        path.rename(trash)
        for leftover in self.root.glob(".trash-*"):
            shutil.rmtree(leftover, ignore_errors=True)

    def usage(self) -> tuple[int, int]:
        """(number of sets, total bytes they take on disk)."""
        sets = self.list()
        total = sum(f.stat().st_size for s in sets for f in s.path.iterdir() if f.is_file())
        return len(sets), total
