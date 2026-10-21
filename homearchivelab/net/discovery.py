"""Find other Home Archive Lab instances on the LAN via UDP broadcast."""
from __future__ import annotations

import json
import socket
import threading
import time

DISCOVERY_PORT = 8766
MAGIC = "HomeArchiveLab/1"


class Discovery:
    """Announces this server (when `port` is set) and collects peers' announcements."""

    def __init__(self, name: str, port: int | None = None, interval: float = 3.0):
        self.name = name
        self.port = port
        self.interval = interval
        self.peers: dict[str, dict] = {}  # "ip:port" -> {name, ip, port, seen}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._my_ips: set[str] = set()

    def start(self) -> None:
        from .server import local_ips

        self._my_ips = set(local_ips()) | {"127.0.0.1"}
        self._stop.clear()
        for target in (self._listen, self._announce):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def active_peers(self, max_age: float = 12.0) -> list[dict]:
        now = time.time()
        return [p for p in self.peers.values() if now - p["seen"] < max_age]

    def probe(self) -> None:
        """Ask everyone to announce now."""
        self._broadcast({"magic": MAGIC, "type": "probe"})

    def _broadcast(self, msg: dict) -> None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(json.dumps(msg).encode(), ("255.255.255.255", DISCOVERY_PORT))
            s.close()
        except OSError:
            pass

    def _hello(self) -> dict:
        return {"magic": MAGIC, "type": "hello", "name": self.name, "port": self.port}

    def _announce(self) -> None:
        while not self._stop.is_set():
            if self.port:
                self._broadcast(self._hello())
            self._stop.wait(self.interval)

    def _listen(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("", DISCOVERY_PORT))
        except OSError:
            return
        s.settimeout(1.0)
        while not self._stop.is_set():
            try:
                data, (ip, _) = s.recvfrom(4096)
                msg = json.loads(data)
            except (socket.timeout, ValueError):
                continue
            except OSError:
                break
            if msg.get("magic") != MAGIC:
                continue
            if msg.get("type") == "probe" and self.port:
                self._broadcast(self._hello())
            elif msg.get("type") == "hello" and msg.get("port"):
                if ip in self._my_ips and msg["port"] == self.port:
                    continue
                key = f"{ip}:{msg['port']}"
                self.peers[key] = {"name": msg.get("name", ip), "ip": ip, "port": msg["port"], "seen": time.time()}
        s.close()
