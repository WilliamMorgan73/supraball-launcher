"""Read and change the game's own settings (display, frame rate, graphics, mouse) in its .ini files.

Edits are line-preserving: only the one key=value line inside the named section changes, so duplicate
keys, other sections, comments and CRLF line endings stay exactly as the game wrote them.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .paths import GamePaths

SYSTEM = "UDKSystemSettings.ini"
ENGINE = "UDKEngine.ini"
INPUT = "UDKInput.ini"


@dataclass(frozen=True)
class Setting:
    file: str
    section: str
    key: str
    kind: str  # "bool" | "int" | "float"
    default: object


# Mouse settings live in the game's own input class; the base [Engine.PlayerInput] values are only defaults.
SETTINGS = {s.key: s for s in [
    Setting(SYSTEM, "SystemSettings", "ResX", "int", 1280),
    Setting(SYSTEM, "SystemSettings", "ResY", "int", 720),
    Setting(SYSTEM, "SystemSettings", "Fullscreen", "bool", False),
    Setting(SYSTEM, "SystemSettings", "UseVsync", "bool", False),
    Setting(SYSTEM, "SystemSettings", "ScreenPercentage", "float", 100.0),
    Setting(SYSTEM, "SystemSettings", "DetailMode", "int", 2),
    Setting(SYSTEM, "SystemSettings", "MaxAnisotropy", "int", 4),
    Setting(SYSTEM, "SystemSettings", "MaxMultiSamples", "int", 1),
    Setting(SYSTEM, "SystemSettings", "DynamicShadows", "bool", True),
    Setting(SYSTEM, "SystemSettings", "MotionBlur", "bool", True),
    Setting(SYSTEM, "SystemSettings", "DepthOfField", "bool", True),
    Setting(SYSTEM, "SystemSettings", "AmbientOcclusion", "bool", True),
    Setting(SYSTEM, "SystemSettings", "Bloom", "bool", True),
    Setting(SYSTEM, "SystemSettings", "bAllowLightShafts", "bool", True),
    Setting(SYSTEM, "SystemSettings", "LensFlares", "bool", True),
    Setting(ENGINE, "Engine.Engine", "bSmoothFrameRate", "bool", True),
    Setting(ENGINE, "Engine.Engine", "MaxSmoothedFrameRate", "int", 62),
    Setting(INPUT, "DBGame.DBPlayerInput", "MouseSensitivity", "float", 14.0),
    Setting(INPUT, "DBGame.DBPlayerInput", "bEnableMouseSmoothing", "bool", False),
    Setting(INPUT, "DBGame.DBPlayerInput", "bInvertMouse", "bool", False),
]}


def _section_span(text: str, section: str) -> tuple[int, int] | None:
    """Start and end offsets of a section's body (after its header line, up to the next header)."""
    header = re.search(rf"^\[{re.escape(section)}\][^\n]*\n?", text, re.M | re.I)
    if not header:
        return None
    nxt = re.compile(r"^\[", re.M).search(text, header.end())
    return header.end(), nxt.start() if nxt else len(text)


def get_value(text: str, section: str, key: str) -> str | None:
    span = _section_span(text, section)
    if not span:
        return None
    m = re.compile(rf"^{re.escape(key)}=([^\r\n]*)", re.M | re.I).search(text, *span)
    return m.group(1) if m else None


def set_value(text: str, section: str, key: str, value: str) -> str:
    """Change the first key= line in [section], adding the line (or the section) if it's missing."""
    nl = "\r\n" if "\r\n" in text else "\n"
    span = _section_span(text, section)
    if not span:
        sep = "" if not text or text.endswith("\n") else nl
        return f"{text}{sep}{nl}[{section}]{nl}{key}={value}{nl}"
    m = re.compile(rf"^({re.escape(key)}=)[^\r\n]*", re.M | re.I).search(text, *span)
    if m:
        return text[:m.start()] + m.group(1) + value + text[m.end():]
    # Append after the section's last non-blank line.
    body_end = span[0] + len(text[span[0]:span[1]].rstrip("\r\n"))
    if body_end > span[0]:
        return text[:body_end] + nl + f"{key}={value}" + text[body_end:]
    return text[:span[0]] + f"{key}={value}{nl}" + text[span[0]:]


def parse(setting: Setting, raw: str | None):
    if raw is None:
        return setting.default
    raw = raw.strip()
    try:
        if setting.kind == "bool":
            return raw.lower() in ("true", "1", "yes")
        if setting.kind == "int":
            return int(float(raw))
        return float(raw)
    except ValueError:
        return setting.default


def format_value(setting: Setting, value) -> str:
    if setting.kind == "bool":
        return "True" if value else "False"
    if setting.kind == "int":
        return str(int(value))
    return f"{float(value):.6f}"


def _read(path: Path) -> str:
    with path.open(encoding="utf-8", errors="replace", newline="") as f:  # newline="" keeps CRLF
        return f.read()


def load(paths: GamePaths) -> dict:
    texts: dict[str, str] = {}
    values = {}
    for key, s in SETTINGS.items():
        if s.file not in texts:
            try:
                texts[s.file] = _read(paths.config_file(s.file))
            except OSError:
                texts[s.file] = ""
        values[key] = parse(s, get_value(texts[s.file], s.section, s.key))
    return values


def save(paths: GamePaths, values: dict) -> list[Path]:
    """Write changed values. Each file that changes gets a timestamped backup first. Returns those files."""
    by_file: dict[str, list[Setting]] = {}
    for key in values:
        s = SETTINGS[key]
        by_file.setdefault(s.file, []).append(s)
    written = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name, settings in by_file.items():
        path = paths.config_file(name)
        old = _read(path) if path.exists() else ""
        new = old
        for s in settings:
            if parse(s, get_value(new, s.section, s.key)) != values[s.key]:
                new = set_value(new, s.section, s.key, format_value(s, values[s.key]))
        if new == old:
            continue
        if path.exists():
            shutil.copy2(path, path.with_name(f"{path.name}.bak-{stamp}"))
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write(new)
        written.append(path)
    return written


def game_running() -> bool:
    """Whether the game client (not a dedicated server) is running; it rewrites these files on exit."""
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == os.getpid():
            continue
        try:
            argv = (d / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except OSError:
            continue
        if any(a.lower().endswith("udk.exe") for a in argv) and "server" not in (a.lower() for a in argv):
            return True
    return False
