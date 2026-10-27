"""Costume artwork from the official launcher: character previews and item icons.

The official launcher draws a player from 280x467 layers: a pitch background, the skin (masked by
SkinAlpha.png), a grass foreground (masked by ForegroundA.png), then the hat (masked by <id>a.png).
The art is extracted from the user's install into a cache on first use, never shipped with this repo.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from ..paths import GamePaths
from ..qt_resources import ResourceError, extract

SIZE = (280, 467)
# Where each slot's artwork sits inside the 280x467 canvas (measured from the masks), for item icons.
ICON_CROP = {"skin": QRect(40, 76, 210, 376), "hat": QRect(80, 20, 130, 130)}


def art_cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "supraball-launcher" / "art"


def ensure_art(paths: GamePaths) -> Path | None:
    """Directory holding images/Skins and images/Hats, extracting it if needed. None if unavailable."""
    exe = paths.game_dir / "launcher/supraball-launcher.exe"
    try:
        stat = exe.stat()
    except OSError:
        return None
    # Keyed on the exe's size and mtime, so a game update re-extracts.
    root = art_cache_root() / f"{stat.st_size}-{int(stat.st_mtime)}"
    done = root / ".complete"
    if not done.exists():
        try:
            extract(exe, "images", root, ("images/Skins/", "images/Hats/"))
        except (ResourceError, OSError, ValueError):
            return None
        done.touch()
    return root / "images"


class CostumeArt:
    def __init__(self, images: Path | None):
        self.images = images
        self._cache: dict[str, QImage | None] = {}

    @property
    def available(self) -> bool:
        return self.images is not None and (self.images / "Skins/SkinAlpha.png").exists()

    def _masked(self, colour: str, mask: str) -> QImage | None:
        key = f"{colour}|{mask}"
        if key not in self._cache:
            img = QImage(str(self.images / colour)) if self.images else QImage()
            alpha = QImage(str(self.images / mask)) if self.images else QImage()
            if img.isNull() or alpha.isNull():
                self._cache[key] = None
            else:
                img = img.convertToFormat(QImage.Format_ARGB32)
                img.setAlphaChannel(alpha.convertToFormat(QImage.Format_Grayscale8))
                self._cache[key] = img
        return self._cache[key]

    def skin(self, definition: int) -> QImage | None:
        return self._masked(f"Skins/{definition}.png", "Skins/SkinAlpha.png")

    def hat(self, definition: int) -> QImage | None:
        return self._masked(f"Hats/{definition}.png", f"Hats/{definition}a.png")

    def has_art(self, slot: str, definition: int) -> bool:
        return self.available and (self.images / ("Skins" if slot == "skin" else "Hats") / f"{definition}.png").exists() \
            if slot in ("skin", "hat") else False

    def character(self, skin: int | None, hat: int | None) -> QPixmap:
        """The player as the official launcher shows them. Without a skin, a faint silhouette."""
        canvas = QImage(*SIZE, QImage.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        background = QImage(str(self.images / "Skins/Background.png")) if self.images else QImage()
        if not background.isNull():
            p.drawImage(0, 0, background)
        skin_img = self.skin(skin) if skin is not None else None
        if skin_img is None:
            silhouette = self._masked("Skins/SkinAlpha.png", "Skins/SkinAlpha.png")
            if silhouette is not None:
                tinted = QImage(silhouette)
                tp = QPainter(tinted)
                tp.setCompositionMode(QPainter.CompositionMode_SourceIn)
                tp.fillRect(tinted.rect(), QColor(242, 247, 243, 70))
                tp.end()
                p.drawImage(0, 0, tinted)
        else:
            p.drawImage(0, 0, skin_img)
        foreground = self._masked("Skins/Foreground.png", "Skins/ForegroundA.png")
        if foreground is not None:
            p.drawImage(0, 0, foreground)
        hat_img = self.hat(hat) if hat is not None else None
        if hat_img is not None:
            p.drawImage(0, 0, hat_img)
        p.end()
        return QPixmap.fromImage(canvas)

    def icon(self, slot: str, definition: int) -> QPixmap | None:
        if not self.has_art(slot, definition):
            return None
        img = self.skin(definition) if slot == "skin" else self.hat(definition)
        if img is None:
            return None
        return QPixmap.fromImage(img.copy(ICON_CROP[slot]))
