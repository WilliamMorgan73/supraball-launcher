"""Ask Steam (through a small helper run under Proton) for a sign-in ticket, the player's
identity, and their Supraball inventory."""

from __future__ import annotations

import json
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from . import game
from .paths import APP_ID, GamePaths

HELPER = Path(__file__).resolve().parent.parent / "tools/steamhelper/steamhelper.exe"

ERRORS = {
    3: "Couldn't load the official launcher's steam_api.dll. Verify the game files in Steam.",
    4: "Steam didn't respond. Make sure Steam is running and you're signed in.",
    5: "Steam is missing an interface this launcher needs.",
    6: "Steam didn't hand out a sign-in ticket in time. Try again in a minute.",
    7: "Steam didn't return your inventory in time. Try again in a minute.",
}


class SteamError(RuntimeError):
    pass


@dataclass
class Item:
    definition: int
    name: str
    slot: str  # "skin", "hat", "gun", or "" for things that can't be worn
    icon_url: str = ""
    quality: int = 0
    color: str = ""  # hex, from the item definition's name_color/background_color
    owned: bool = True
    marketable: bool = False


@dataclass
class SteamSession:
    steamid: int
    name: str
    country: str
    ticket: bytes
    items: list[Item] = field(default_factory=list)  # one per owned definition, wearable first
    catalogue: list[Item] = field(default_factory=list)  # every wearable definition in the game


def wine_path(path: Path) -> str:
    """Wine maps the Linux root to drive Z:."""
    return "Z:" + str(path.resolve()).replace("/", "\\")


def _item(definition: int, props: dict, owned: bool) -> Item:
    try:
        quality = int(props.get("item_quality", 0))
    except ValueError:
        quality = 0
    slot = (props.get("item_slot") or "").lower()
    return Item(
        definition=definition,
        name=props.get("name") or f"Item {definition}",
        slot=slot if slot in ("skin", "hat", "gun") else "",
        icon_url=props.get("icon_url", ""),
        quality=quality,
        color=props.get("name_color") or props.get("background_color") or "",
        owned=owned,
        marketable=props.get("marketable") in ("1", "true"),
    )


def _sort_key(item: Item):
    return item.slot == "", item.slot, item.name.lower()


def parse(data: dict) -> SteamSession:
    defs = data.get("defs", {})
    owned = {i["def"] for i in data.get("items", [])}
    items = sorted((_item(d, defs.get(str(d), {}), True) for d in owned), key=_sort_key)
    catalogue = []
    for key, props in defs.items():
        item = _item(int(key), props, int(key) in owned)
        if item.slot:
            catalogue.append(item)
    catalogue.sort(key=_sort_key)
    return SteamSession(
        steamid=int(data["steamid"]),
        name=data.get("name", ""),
        country=data.get("country", ""),
        ticket=bytes.fromhex(data["ticket"]),
        items=items,
        catalogue=catalogue,
    )


def market_url(item: Item) -> str:
    return f"https://steamcommunity.com/market/listings/{APP_ID}/{urllib.parse.quote(item.name, safe='')}"


def fetch(paths: GamePaths, timeout: float = 90) -> SteamSession:
    dll = paths.game_dir / "launcher/steam_api.dll"
    with tempfile.TemporaryDirectory(prefix="sbl-steam-") as tmp:
        out = Path(tmp) / "steam.json"
        argv, env = game.proton_command(paths, [wine_path(dll), wine_path(out)], exe=HELPER)
        try:
            proc = subprocess.run(argv, env=env, cwd=dll.parent, timeout=timeout,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            raise SteamError("Timed out waiting for Steam.") from e
        if proc.returncode != 0 or not out.exists():
            raise SteamError(ERRORS.get(proc.returncode, f"Steam helper failed (exit code {proc.returncode})."))
        return parse(json.loads(out.read_text(encoding="utf-8", errors="replace")))
