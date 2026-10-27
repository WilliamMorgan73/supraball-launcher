"""Interop with the official Supraball launcher: open it, and mark its tutorial as done."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from . import game
from .paths import GamePaths

REG_KEY = r"HKEY_CURRENT_USER\Software\Supra Games\Supraball Launcher"
# QSettings stores bools as the strings "true"/"false" in the registry.
TUTORIAL_FLAGS = ("tutorial_played", "new_tutorial_played", "tutorial_license")
TASK_COUNT = 80  # DBTrainingTaskStatus.taskStatus[80]


def official_exe(paths: GamePaths) -> Path:
    return paths.game_dir / "launcher/supraball-launcher.exe"


def open_official(paths: GamePaths) -> subprocess.Popen:
    # It finds the game as Binaries/Win32/UDK.exe relative to its working directory, like Steam starts it.
    return game.launch_detached(paths, [], official_exe(paths), cwd=paths.game_dir)


def training_ini(paths: GamePaths) -> Path:
    return paths.config_file("UDKTraining.ini")


def complete_training_tasks(text: str) -> str:
    """Mark every tutorial/training task done (the game writes taskStatus[n]=1 when you finish one)."""
    body = "\n".join(f"taskStatus[{i}]=1" for i in range(TASK_COUNT))
    section = f"[DBGame.DBTrainingTaskStatus]\n{body}\n"
    pattern = re.compile(r"^\[DBGame\.DBTrainingTaskStatus\]\n(?:(?!\[).*\n?)*", re.M)
    if pattern.search(text):
        return pattern.sub(lambda _: section + "\n", text, count=1).rstrip("\n") + "\n"
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + section


def registry_file() -> str:
    lines = ["Windows Registry Editor Version 5.00", "", f"[{REG_KEY}]"]
    lines += [f'"{name}"="true"' for name in TUTORIAL_FLAGS]
    return "\r\n".join(lines) + "\r\n"


def unlock_tutorial(paths: GamePaths, timeout: float = 120) -> None:
    """Make the official launcher treat the tutorial as completed in this Proton prefix."""
    ini = training_ini(paths)
    text = ini.read_text(encoding="utf-8", errors="replace") if ini.exists() else ""
    new = complete_training_tasks(text)
    if new != text:
        if ini.exists():
            shutil.copy2(ini, ini.with_name(f"{ini.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
        ini.write_text(new, encoding="utf-8")

    # Import the flags with Wine's reg.exe so the prefix's registry is updated safely.
    reg_path = paths.compat_data / "pfx/drive_c/supraball-launcher-tutorial.reg"
    reg_path.write_text(registry_file(), encoding="utf-8")
    try:
        argv, env = game.proton_command(paths, ["import", r"C:\supraball-launcher-tutorial.reg"],
                                        exe=r"C:\windows\system32\reg.exe")
        subprocess.run(argv, env=env, cwd=paths.game_dir, timeout=timeout, check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        reg_path.unlink(missing_ok=True)


def tutorial_unlocked(paths: GamePaths) -> bool:
    user_reg = paths.compat_data / "pfx/user.reg"
    try:
        reg = user_reg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    m = re.search(r"^\[Software\\\\Supra Games\\\\Supraball Launcher\][^\n]*\n(.*?)(?=^\[|\Z)", reg, re.M | re.S)
    return bool(m) and all(f'"{name}"="true"' in m.group(1) for name in TUTORIAL_FLAGS)
