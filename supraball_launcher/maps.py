"""Discover playable Supraball maps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# From DBGame.InitGame: these maps are played 3v3, everything else 5v5.
THREE_V_THREE = {"db-hall", "db-hall2", "db-cave", "db-smallpitch", "db-hall_night"}
NOT_PLAYABLE = {"db-frontendmap"}

FALLBACK_MAPS = [
    "DB-Beach", "DB-Castle", "DB-Cave", "DB-Desert", "DB-Hall", "DB-Hall_night", "DB-Moon",
    "DB-Pitch", "DB-Pitch_Rain", "DB-Pitch_Snow", "DB-Skill", "DB-SmallPitch", "DB-Stadium",
    "DB-TrainingPitch", "DB-Tutorial", "DB-Volcano",
]


@dataclass(frozen=True)
class MapInfo:
    name: str

    @property
    def is_3v3(self) -> bool:
        return self.name.lower() in THREE_V_THREE

    @property
    def team_size(self) -> int:
        return 3 if self.is_3v3 else 5

    @property
    def label(self) -> str:
        return f"{self.name}  ({self.team_size}v{self.team_size})"


def scan_maps(game_dir: Path | None) -> list[MapInfo]:
    names: set[str] = set()
    if game_dir:
        for f in (game_dir / "UDKGame/CookedPC").rglob("DB-*.udk"):
            stem = f.stem
            # Skip sync-conflict copies like "DB-TrainingPitch (SFConflict ...)".
            if " " in stem or "(" in stem or stem.lower() in NOT_PLAYABLE:
                continue
            names.add(stem)
    if not names:
        names = set(FALLBACK_MAPS)
    return [MapInfo(n) for n in sorted(names, key=str.lower)]


def display_name(master_map: str) -> str:
    """The master server reports maps as e.g. 'smallpitch'; show them as 'SmallPitch'."""
    lowered = master_map.lower().removeprefix("db-")
    for name in FALLBACK_MAPS:
        if name.lower().removeprefix("db-") == lowered:
            return name.removeprefix("DB-")
    return master_map
