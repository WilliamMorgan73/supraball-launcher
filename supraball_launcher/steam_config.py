"""Set Supraball's Steam launch options so Steam's Play button opens this launcher.

Steam keeps per-game launch options in userdata/<id>/config/localconfig.vdf under
UserLocalConfigStore > Software > Valve > Steam > apps > <appid> > LaunchOptions.
Steam rewrites that file on exit, so it must not be running while we edit it.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from .paths import APP_ID, find_steam_root

STEAM_LAUNCH_SCRIPT = Path(__file__).resolve().parent.parent / "steam-launch.sh"
APP_PATH = ["userlocalconfigstore", "software", "valve", "steam", "apps", str(APP_ID)]
KEY = "LaunchOptions"

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|[{}]')


class SteamConfigError(RuntimeError):
    pass


def launch_option() -> str:
    return f'"{STEAM_LAUNCH_SCRIPT}" %command%'


def vdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def vdf_unescape(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


def _find_block(text: str, path: list[str]) -> tuple[int, int, int] | None:
    """Locate the block at path. Returns (open_brace_index, close_brace_index, open_line_start)."""
    stack: list[str | None] = []
    last: str | None = None
    open_at: list[int] = []
    target = [p.lower() for p in path]
    found_open = None
    for m in _TOKEN.finditer(text):
        tok = m.group(0)
        if tok == "{":
            stack.append(last)
            open_at.append(m.start())
            last = None
            if found_open is None and [s.lower() if s else s for s in stack] == target:
                found_open = m.start()
        elif tok == "}":
            if found_open is not None and open_at and open_at[-1] == found_open:
                line_start = text.rfind("\n", 0, found_open) + 1
                return found_open, m.start(), line_start
            stack.pop()
            open_at.pop()
            last = None
        else:
            # A quoted token is either a key or (if the previous token was a key) its value.
            last = None if last is not None else m.group(1)
    return None


def _direct_key_span(text: str, start: int, end: int, key: str) -> tuple[int, int, int] | None:
    """Within the block body text[start:end], find key at depth 0.

    Returns (line_start, value_start, value_end) where value_* span the quoted value's contents.
    """
    depth = 0
    pending_key: re.Match | None = None
    for m in _TOKEN.finditer(text, start, end):
        tok = m.group(0)
        if tok == "{":
            depth += 1
            pending_key = None
        elif tok == "}":
            depth -= 1
        elif depth == 0:
            if pending_key is None:
                pending_key = m
            else:
                if pending_key.group(1).lower() == key.lower():
                    line_start = text.rfind("\n", 0, pending_key.start()) + 1
                    return line_start, m.start(1), m.end(1)
                pending_key = None
    return None


def set_launch_options(text: str, value: str | None) -> str:
    """Return text with the app's LaunchOptions set to value (None removes it)."""
    block = _find_block(text, APP_PATH)
    if block is None:
        raise SteamConfigError("Supraball has no entry in Steam's localconfig.vdf yet. Launch it from Steam once first.")
    open_brace, close_brace, open_line = block
    existing = _direct_key_span(text, open_brace + 1, close_brace, KEY)
    if existing:
        line_start, v_start, v_end = existing
        if value is None:
            line_end = text.find("\n", v_end)
            return text[:line_start] + text[line_end + 1:]
        return text[:v_start] + vdf_escape(value) + text[v_end:]
    if value is None:
        return text
    indent = re.match(r"[\t ]*", text[open_line:]).group(0) + "\t"
    insert = f'\n{indent}"{KEY}"\t\t"{vdf_escape(value)}"'
    return text[: open_brace + 1] + insert + text[open_brace + 1:]


def get_launch_options(text: str) -> str | None:
    block = _find_block(text, APP_PATH)
    if block is None:
        return None
    span = _direct_key_span(text, block[0] + 1, block[1], KEY)
    return vdf_unescape(text[span[1]:span[2]]) if span else None


def steam_running() -> bool:
    for comm in Path("/proc").glob("[0-9]*/comm"):
        try:
            if comm.read_text().strip() in ("steam", "steamwebhelper"):
                return True
        except OSError:
            continue
    return False


def config_files(steam_root: Path | None = None) -> list[Path]:
    root = steam_root or find_steam_root()
    files = []
    for f in sorted((root / "userdata").glob("*/config/localconfig.vdf")):
        try:
            if _find_block(f.read_text(encoding="utf-8", errors="replace"), APP_PATH):
                files.append(f)
        except OSError:
            continue
    return files


def apply(value: str | None, steam_root: Path | None = None) -> list[Path]:
    """Write value (None to clear) to every Steam account that has Supraball. Returns the files changed."""
    if steam_running():
        raise SteamConfigError("Steam is running. Quit Steam fully (Steam menu > Exit), then try again.")
    files = config_files(steam_root)
    if not files:
        raise SteamConfigError("Couldn't find Supraball in any Steam account's config. Launch it from Steam once first.")
    changed = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        new = set_launch_options(text, value)
        if new != text:
            shutil.copy2(f, f.with_name(f"{f.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
            f.write_text(new, encoding="utf-8")
            changed.append(f)
    return changed


def current(steam_root: Path | None = None) -> str | None:
    for f in config_files(steam_root):
        value = get_launch_options(f.read_text(encoding="utf-8", errors="replace"))
        if value:
            return value
    return None
