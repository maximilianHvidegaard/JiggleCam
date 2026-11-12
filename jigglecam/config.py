"""Configuration loading.

Layering: config/default.toml (committed) <- config/local.toml (gitignored)
<- explicit path passed on the command line. Later files override earlier
ones key by key, so an override file only needs the keys it changes.

The result is a set of frozen dataclasses so typos in key names fail loudly
at startup instead of silently falling back to defaults.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "config" / "default.toml"
LOCAL_PATH = REPO_ROOT / "config" / "local.toml"


@dataclass(frozen=True)
class DisplayConfig:
    fullscreen: bool = True
    hide_cursor: bool = True
    rotation: int = 0
    kms_device: str = "auto"

    def __post_init__(self) -> None:
        if self.rotation not in (0, 90, 180, 270):
            raise ConfigError(f"display.rotation must be 0, 90, 180 or 270, got {self.rotation!r}")


@dataclass(frozen=True)
class PreviewConfig:
    backend: str = "software"
    width: int = 1280
    height: int = 720
    keep_aspect: bool = True

    def __post_init__(self) -> None:
        if self.backend not in ("gl", "software"):
            raise ConfigError(f"preview.backend must be 'gl' or 'software', got {self.backend!r}")


@dataclass(frozen=True)
class CameraConfig:
    index: int = 0
    rotate_180: bool = False


@dataclass(frozen=True)
class UIConfig:
    exit_hold_ms: int = 1000


@dataclass(frozen=True)
class Config:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    preview: PreviewConfig = field(default_factory=PreviewConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    ui: UIConfig = field(default_factory=UIConfig)


class ConfigError(ValueError):
    pass


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _build(cls: type, data: dict[str, Any], path: str = "") -> Any:
    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        where = f"[{path.rstrip('.')}]" if path else "top level"
        raise ConfigError(f"unknown config key(s) at {where}: {sorted(unknown)}")
    kwargs = {}
    for name, value in data.items():
        f = known[name]
        sub = f.default_factory() if callable(f.default_factory) else None  # type: ignore[misc]
        if is_dataclass(sub):
            if not isinstance(value, dict):
                raise ConfigError(f"[{path + name}] must be a table")
            kwargs[name] = _build(type(sub), value, f"{path}{name}.")
        else:
            kwargs[name] = value
    return cls(**kwargs)


def load(extra: Path | None = None) -> Config:
    """Load default.toml, then local.toml, then `extra` if given."""
    data: dict[str, Any] = {}
    for p in (DEFAULT_PATH, LOCAL_PATH, extra):
        if p is not None and Path(p).exists():
            with open(p, "rb") as fh:
                data = _merge(data, tomllib.load(fh))
        elif p is extra and extra is not None:
            raise ConfigError(f"config file not found: {extra}")
    return _build(Config, data)
