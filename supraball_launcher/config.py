"""Launcher settings and server presets, stored as JSON."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .master import MASTER_HOST, MASTER_PORT


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "supraball-launcher"


@dataclass
class Settings:
    game_dir: str = ""  # empty = auto-detect
    proton_dir: str = ""  # empty = auto-detect
    master_host: str = MASTER_HOST
    master_port: int = MASTER_PORT
    auto_refresh: bool = True
    costume_show_all: bool = False  # Costume tab: preview every item, not just owned ones
    last_server: dict = field(default_factory=dict)
    presets: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_dir() / "settings.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(path)
