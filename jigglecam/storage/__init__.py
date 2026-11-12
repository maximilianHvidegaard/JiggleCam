"""Storage layer: writes and reads capture sets on disk. No Qt, no camera."""

from jigglecam.storage.sets import FORMAT_VERSION, SetStore, StoredSet

__all__ = ["FORMAT_VERSION", "SetStore", "StoredSet"]
