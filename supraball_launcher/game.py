"""Build UDK command lines and run them through Proton."""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .paths import APP_ID, GamePaths

# Points the server's master-server client somewhere harmless so it never registers publicly.
PRIVATE_MASTER = "127.0.0.1"


@dataclass
class ServerConfig:
    map: str = "DB-Pitch"
    title: str = "My Supraball Server"
    password: str = ""
    port: int = 7777
    query_port: int = 27015
    max_players: int = 0  # 0 = game picks (6 for 3v3 maps, 10 otherwise)
    max_spectators: int = 2
    bots: int = 0
    bot_skill: int = 0  # 0 = automatic
    goal_score: int = 0  # 0 = game default
    time_limit: int = 0  # minutes, 0 = game default
    golden_goal: bool = False
    matchmaking: bool = False  # True = wait for full teams + countdown (lobby style)
    ranked: bool = False
    public: bool = True
    server_ip: str = ""  # public IP to advertise; empty lets the master server work it out

    @classmethod
    def from_dict(cls, data: dict) -> "ServerConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


def sanitize(value: str) -> str:
    """Strip characters that would break UE3 URL option parsing."""
    return "".join(c for c in value if c not in '?"#\n\r\t').strip()


def flag(value: bool) -> str:
    return "true" if value else "false"


def build_server_url(cfg: ServerConfig) -> str:
    opts: list[tuple[str, str]] = [
        ("MatchTitle", sanitize(cfg.title) or "My Supraball Server"),
        ("bMatchmaking", flag(cfg.matchmaking)),
        ("bRanked", flag(cfg.ranked)),
        ("bGoldenGoal", flag(cfg.golden_goal)),
        ("QueryPort", str(cfg.query_port)),
        ("MaxSpectators", str(cfg.max_spectators)),
    ]
    if cfg.password:
        opts.append(("MatchPassword", sanitize(cfg.password)))
    if cfg.max_players:
        opts.append(("MaxPlayers", str(cfg.max_players)))
    if cfg.bots:
        opts.append(("NumPlay", str(cfg.bots)))
    if cfg.bot_skill:
        opts.append(("BotSkill", str(cfg.bot_skill)))
    if cfg.goal_score:
        opts.append(("GoalScore", str(cfg.goal_score)))
    if cfg.time_limit:
        opts.append(("TimeLimit", str(cfg.time_limit)))
    if cfg.server_ip:
        opts.append(("ServerIP", sanitize(cfg.server_ip)))
    if not cfg.public:
        opts.append(("master", PRIVATE_MASTER))
    return sanitize(cfg.map) + "".join(f"?{k}={v}" for k, v in opts)


# DBGame saves these to UDKDeathball.ini and only overrides them when the URL option is non-empty,
# so a password or IP from an earlier run would otherwise stick to every later server.
STICKY_OPTIONS = ("MatchPassword", "ServerIP", "BetaMasterHost")


def clear_sticky_options(text: str) -> str:
    """Blank the sticky DBGame options in UDKDeathball.ini's text."""
    return re.sub(rf"^({'|'.join(STICKY_OPTIONS)})=[^\r\n]*$", r"\1=", text, flags=re.M | re.I)


def reset_server_ini(paths: GamePaths) -> None:
    ini = paths.config_file("UDKDeathball.ini")
    try:
        text = ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    new = clear_sticky_options(text)
    if new != text:
        ini.write_text(new, encoding="utf-8")


@dataclass
class ServerEvent:
    kind: str  # "listed" | "rejected" | "unreachable" | "port_in_use"
    detail: str = ""


_MASTER_RESPONSE = re.compile(r"Masterserver response:\s*(.*)$")


def parse_server_event(line: str) -> ServerEvent | None:
    """Pick out the server log lines that say whether the master server listed us."""
    if m := _MASTER_RESPONSE.search(line):
        try:
            reply = json.loads(m.group(1))
        except ValueError:
            reply = None
        if isinstance(reply, dict) and reply.get("error"):
            return ServerEvent("rejected", str(reply["error"]))
        return ServerEvent("listed")
    if "Failed to reach masterserver" in line:
        return ServerEvent("unreachable")
    if "QueryLog: Bind failed" in line:
        return ServerEvent("port_in_use")
    return None


def explain(event: ServerEvent, cfg: ServerConfig) -> str:
    if event.kind == "listed":
        return "The master server accepted your server. It should show in the public browser."
    if event.kind == "unreachable":
        return "Can't reach the master server, so your server isn't listed publicly. Players can still join by IP."
    if event.kind == "port_in_use":
        return (f"Query port {cfg.query_port} is already in use, so the server browser may not see "
                "your player count or ping. Pick another query port if this matters.")
    if "invalid ip" in event.detail.lower():
        return ("The master server can't use your address, so your server isn't listed. This usually means "
                "your network blocks incoming connections (university, office or mobile networks). "
                "Set Public IP if you know it, or host a private server over a LAN or VPN.")
    return f"The master server didn't list your server: {event.detail}"


def server_log_name(cfg: ServerConfig) -> str:
    return f"sbl-server-{cfg.port}.log"


def build_server_args(cfg: ServerConfig) -> list[str]:
    return [
        "server",
        build_server_url(cfg),
        f"-port={cfg.port}",
        f"LOG={server_log_name(cfg)}",
        "-forcelogflush",
        "-unattended",
    ]


def build_join_args(host: str, port: int, password: str = "") -> list[str]:
    url = f"{sanitize(host)}:{port}"
    if password:
        url += f"?Password={sanitize(password)}"
    return [url]


def proton_command(paths: GamePaths, udk_args: list[str], exe: str | Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Full argv + environment to run UDK.exe (or another Windows program) the same way Steam would."""
    env = dict(os.environ)
    env.update(
        STEAM_COMPAT_DATA_PATH=str(paths.compat_data),
        STEAM_COMPAT_CLIENT_INSTALL_PATH=str(paths.steam_root),
        STEAM_COMPAT_INSTALL_PATH=str(paths.game_dir),
        SteamAppId=str(APP_ID),
        SteamGameId=str(APP_ID),
        WINEDEBUG=env.get("WINEDEBUG", "-all"),
    )
    proton = [str(paths.proton_dir / "proton"), "waitforexitandrun", str(exe or paths.exe), *udk_args]
    if paths.runtime_dir:
        argv = [str(paths.runtime_dir / "_v2-entry-point"), "--verb=waitforexitandrun", "--", *proton]
    else:
        argv = proton
    return argv, env


def shell_preview(udk_args: list[str]) -> str:
    """Human-readable UDK.exe command line, e.g. for a Windows box or a script."""
    quoted = [f'"{a}"' if " " in a else a for a in udk_args]
    return "UDK.exe " + " ".join(quoted)


def launch_detached(paths: GamePaths, udk_args: list[str], exe: Path | None = None,
                    cwd: Path | None = None) -> subprocess.Popen:
    argv, env = proton_command(paths, udk_args, exe)
    return subprocess.Popen(
        argv, env=env, cwd=cwd or (exe or paths.exe).parent,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def find_server_pids(cfg: ServerConfig) -> list[int]:
    """PIDs launched for this server: UDK.exe and its Proton wrappers (Wine keeps argv visible in /proc).

    Matches whole argv elements so unrelated processes that merely mention the log name are left alone.
    """
    marker = f"LOG={server_log_name(cfg)}"
    pids = []
    me = os.getpid()
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == me:
            continue
        try:
            argv = (d / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except OSError:
            continue
        if marker in argv and any(a.lower().endswith("udk.exe") for a in argv):
            pids.append(int(d.name))
    return pids


class ServerProcess:
    """One running dedicated server. Call poll() regularly to collect output lines."""

    def __init__(self, paths: GamePaths, cfg: ServerConfig):
        self.paths = paths
        self.cfg = cfg
        self.log_path = paths.logs_dir / server_log_name(cfg)
        self.proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._log_pos = 0

    def start(self) -> None:
        if self.log_path.exists():
            self.log_path.unlink()
        reset_server_ini(self.paths)
        argv, env = proton_command(self.paths, build_server_args(self.cfg))
        self.proc = subprocess.Popen(
            argv, env=env, cwd=self.paths.exe.parent,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in self.proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if line:
                self._lines.put(f"[proton] {line}")

    def poll(self) -> list[str]:
        """New output since the last call: Proton's stdout plus the UDK log file."""
        out: list[str] = []
        while not self._lines.empty():
            out.append(self._lines.get_nowait())
        try:
            with self.log_path.open("rb") as f:
                f.seek(self._log_pos)
                chunk = f.read()
        except OSError:
            chunk = b""
        if chunk:
            # Only consume whole lines; keep a partial last line for next time.
            end = chunk.rfind(b"\n") + 1
            if end:
                self._log_pos += end
                text = chunk[:end].decode("utf-8", errors="replace")
                out.extend(line.rstrip("\r") for line in text.splitlines() if line.strip())
        return out

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, timeout: float = 8.0) -> None:
        if not self.proc:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in find_server_pids(self.cfg):
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + timeout / 2
            while time.monotonic() < deadline and find_server_pids(self.cfg):
                time.sleep(0.2)
        # Proton/the runtime wrapper exit by themselves once UDK.exe is gone.
        try:
            self.proc.wait(timeout=timeout / 2)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
