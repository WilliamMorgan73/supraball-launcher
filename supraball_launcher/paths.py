"""Locate Steam, the Supraball install, its Proton prefix and the Proton build to run it with."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

APP_ID = 321400

STEAM_ROOT_CANDIDATES = [
    Path.home() / ".local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
]


class PathError(RuntimeError):
    pass


@dataclass
class GamePaths:
    steam_root: Path
    game_dir: Path
    compat_data: Path
    proton_dir: Path
    runtime_dir: Path | None  # Steam Linux Runtime container Proton wants, if installed

    @property
    def exe(self) -> Path:
        return self.game_dir / "Binaries/Win64/UDK.exe"

    @property
    def logs_dir(self) -> Path:
        return self.game_dir / "UDKGame/Logs"

    def config_file(self, name: str) -> Path:
        """A file in UDKGame/Config, matched case-insensitively (Wine doesn't care about case, Linux does)."""
        config = self.game_dir / "UDKGame/Config"
        for f in config.glob("*.ini"):
            if f.name.lower() == name.lower():
                return f
        return config / name


def parse_library_paths(vdf_text: str) -> list[Path]:
    return [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf_text)]


def parse_vdf_value(vdf_text: str, key: str) -> str | None:
    m = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', vdf_text)
    return m.group(1) if m else None


def find_steam_root() -> Path:
    for root in STEAM_ROOT_CANDIDATES:
        if (root / "steamapps").is_dir():
            return root.resolve()
    raise PathError("Could not find a Steam installation.")


def library_folders(steam_root: Path) -> list[Path]:
    libs = [steam_root]
    vdf = steam_root / "steamapps/libraryfolders.vdf"
    if vdf.is_file():
        for p in parse_library_paths(vdf.read_text(errors="replace")):
            if p.resolve() not in libs:
                libs.append(p.resolve())
    return libs


def find_app_dir(libs: list[Path], app_id: int) -> Path | None:
    """Return the install directory for an app id by reading its appmanifest."""
    for lib in libs:
        manifest = lib / f"steamapps/appmanifest_{app_id}.acf"
        if manifest.is_file():
            installdir = parse_vdf_value(manifest.read_text(errors="replace"), "installdir")
            if installdir:
                d = lib / "steamapps/common" / installdir
                if d.is_dir():
                    return d
    return None


def proton_from_config_info(compat_data: Path) -> Path | None:
    """compatdata/<id>/config_info records the Proton build last used for the prefix."""
    info = compat_data / "config_info"
    if not info.is_file():
        return None
    for line in info.read_text(errors="replace").splitlines():
        if "/files/" in line:
            d = Path(line.split("/files/")[0])
            if (d / "proton").is_file():
                return d
    return None


def find_any_proton(libs: list[Path]) -> Path | None:
    found = [p.parent for lib in libs for p in (lib / "steamapps/common").glob("Proton*/proton")]
    if not found:
        return None
    # Prefer Experimental, then the highest-sorting version name.
    found.sort(key=lambda d: ("Experimental" in d.name, d.name))
    return found[-1]


def find_runtime(libs: list[Path], proton_dir: Path) -> Path | None:
    manifest = proton_dir / "toolmanifest.vdf"
    if not manifest.is_file():
        return None
    tool_id = parse_vdf_value(manifest.read_text(errors="replace"), "require_tool_appid")
    if not tool_id:
        return None
    d = find_app_dir(libs, int(tool_id))
    return d if d and (d / "_v2-entry-point").is_file() else None


def detect(game_dir: str = "", proton_dir: str = "") -> GamePaths:
    """Auto-detect all paths; non-empty arguments override detection."""
    steam_root = find_steam_root()
    libs = library_folders(steam_root)

    gdir = Path(game_dir).expanduser() if game_dir else find_app_dir(libs, APP_ID)
    if not gdir or not (gdir / "Binaries/Win64/UDK.exe").is_file():
        raise PathError("Could not find Supraball (Binaries/Win64/UDK.exe). Set the game folder in Settings.")

    # The prefix lives in the library that holds the game.
    compat_data = gdir.parent.parent / "compatdata" / str(APP_ID)
    if not compat_data.is_dir():
        compat_data = steam_root / "steamapps/compatdata" / str(APP_ID)

    if proton_dir:
        pdir = Path(proton_dir).expanduser()
    else:
        pdir = proton_from_config_info(compat_data) or find_any_proton(libs)
    if not pdir or not (pdir / "proton").is_file():
        raise PathError("Could not find a Proton installation. Install Proton in Steam or set it in Settings.")

    return GamePaths(
        steam_root=steam_root,
        game_dir=gdir,
        compat_data=compat_data,
        proton_dir=pdir,
        runtime_dir=find_runtime(libs, pdir),
    )
