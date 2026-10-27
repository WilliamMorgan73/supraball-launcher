"""Work out whether players on the internet are likely to reach a server hosted on this machine.

A real UDP reachability test needs a machine outside the network to send packets in, so this only
reports what sits between us and the internet, plus whether the master server listed us.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from dataclasses import dataclass

from .master import ServerEntry

PUBLIC_IP_URL = "https://api.ipify.org"
CGNAT = ipaddress.ip_network("100.64.0.0/10")


@dataclass
class Reachability:
    verdict: str  # "direct" | "nat" | "cgnat" | "unknown"
    local: str
    public: str
    message: str


def local_ipv4() -> str:
    """The address this machine uses for internet traffic. Connecting a UDP socket sends nothing."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("1.1.1.1", 53))
        return s.getsockname()[0]


def public_ipv4(timeout: float = 5.0) -> str:
    with urllib.request.urlopen(PUBLIC_IP_URL, timeout=timeout) as resp:
        text = resp.read(64).decode("ascii", errors="replace").strip()
    return str(ipaddress.IPv4Address(text))


def classify(local: str, public: str, port: int, query_port: int) -> Reachability:
    if not local or not public:
        return Reachability("unknown", local, public,
                            "Couldn't work out your public address. Check your internet connection.")
    ports = f"UDP {port} and {query_port}"
    if local == public:
        return Reachability("direct", local, public,
                            f"This machine has a public address ({public}). Players can join if your "
                            f"firewall allows {ports}.")
    if ipaddress.ip_address(local) in CGNAT or ipaddress.ip_address(public) in CGNAT:
        return Reachability("cgnat", local, public,
                            "Your provider shares one public address between many customers (carrier-grade "
                            "NAT), so port forwarding won't work. Host a private server over a VPN instead.")
    return Reachability("nat", local, public,
                        f"You're behind a router: public address {public}, this machine {local}. Forward "
                        f"{ports} to {local} so players can join. On a university, office or mobile network "
                        "you usually can't, so host a private server over a LAN or VPN instead.")


def check(port: int, query_port: int) -> Reachability:
    try:
        local = local_ipv4()
    except OSError:
        local = ""
    try:
        public = public_ipv4()
    except (OSError, ValueError):
        public = ""
    return classify(local, public, port, query_port)


def find_listed(entries: list[ServerEntry], public_ip: str, port: int) -> ServerEntry | None:
    """Our server in the master server's list, if it's there."""
    return next((e for e in entries if e.ip == public_ip and e.port == port), None)
