"""CaptureController: the single shutter entry point. No Qt in here.

    shutter (screen button now, GPIO button in phase 5)
        -> controller.trigger()                    returns immediately
            capture thread:  source.capture()      viewfinder blacks out ~0.3 s
                             -> event "captured"   shutter can fire again
            storage thread:  store.save(frameset)  JPEG encoding, ~1 s
                             -> event "saved"      UI updates the thumbnail

Two single-worker threads, so you can take the next shot while the previous
one is still being written to the SD card. Saves happen in shutter order.

Events are delivered by calling on_event(event) **from a worker thread**.
The UI must hop back to its own thread (the Qt side uses a signal for this).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from jigglecam.capture.base import CaptureSource, FrameSet
from jigglecam.storage import SetStore


@dataclass(frozen=True)
class CaptureEvent:
    kind: str          # "started" | "captured" | "saved" | "failed" | "busy"
    detail: Any = None  # FrameSet for captured, StoredSet for saved, str for failed


class CaptureController:
    def __init__(self, source: CaptureSource, store: SetStore, on_event: Callable[[CaptureEvent], None]):
        self.source = source
        self.store = store
        self._on_event = on_event
        self._capture_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="capture")
        self._save_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="storage")
        self._lock = threading.Lock()
        self._capturing = False

    @property
    def capturing(self) -> bool:
        return self._capturing

    def trigger(self) -> bool:
        """Request a capture. Returns False (and emits "busy") if one is running."""
        with self._lock:
            if self._capturing:
                self._emit("busy")
                return False
            self._capturing = True
        self._capture_pool.submit(self._capture_job)
        return True

    def _capture_job(self) -> None:
        try:
            self._emit("started")
            fs = self.source.capture()
        except Exception as exc:
            self._emit("failed", f"capture: {exc}")
            return
        finally:
            with self._lock:
                self._capturing = False
        self._emit("captured", fs)
        self._save_pool.submit(self._save_job, fs)

    def _save_job(self, fs: FrameSet) -> None:
        try:
            stored = self.store.save(fs)
        except Exception as exc:
            self._emit("failed", f"save: {type(exc).__name__}: {exc}")
            return
        self._emit("saved", stored)

    def _emit(self, kind: str, detail: Any = None) -> None:
        try:
            self._on_event(CaptureEvent(kind, detail))
        except Exception:  # a broken listener must not kill the worker
            pass

    def shutdown(self) -> None:
        """Finish the running capture and pending saves, then stop the threads."""
        self._capture_pool.shutdown(wait=True)
        self._save_pool.shutdown(wait=True)
