"""LAN server: share a library folder with phones/PCs on the local network.

Endpoints (all JSON unless noted, PIN via `X-PIN` header, `pin` query or cookie):
  GET  /                      web gallery (HTML)
  GET  /api/info              {name, version, upload, auth}
  GET  /api/list?path=        {path, folders:[...], files:[{name,size,kind,mtime}]}
  GET  /api/thumb?path=       JPEG thumbnail
  GET  /api/file?path=        raw file, supports HTTP Range (video streaming)
  POST /api/upload?path=      raw body, file name in `X-Filename` (URL-encoded)
"""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__
from ..core.media import is_media, kind_of, load_preview
from ..core.settings import Settings
from .webui import PAGE


def local_ips() -> list[str]:
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


class _Handler(BaseHTTPRequestHandler):
    server: "ArchiveServer"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # route to the GUI log instead of stderr
        if "/api/thumb" in self.path or "/api/info" in self.path:
            return
        if self.server.on_log:
            self.server.on_log(f"{self.client_address[0]} — {fmt % args}")

    # ---- helpers -------------------------------------------------------
    def _query(self) -> dict[str, str]:
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}

    def _authorized(self) -> bool:
        pin = self.server.pin
        if not pin:
            return True
        given = self.headers.get("X-PIN") or self._query().get("pin", "")
        if not given:
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "hal_pin":
                    given = urllib.parse.unquote(v)
        return given == pin

    def _resolve(self, rel: str) -> Path | None:
        root = self.server.root.resolve()
        target = (root / rel.strip("/\\")).resolve()
        if target != root and root not in target.parents:
            return None
        return target

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    # ---- routes --------------------------------------------------------
    def do_GET(self):  # noqa: N802
        route = urllib.parse.urlparse(self.path).path
        if route in ("/", "/index.html"):
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if route == "/api/info":
            return self._json({"name": self.server.name, "version": __version__, "app": "HomeArchiveLab",
                               "upload": self.server.allow_upload, "auth": bool(self.server.pin)})
        if not self._authorized():
            return self._json({"error": "pin"}, 401)
        q = self._query()
        if route == "/api/list":
            return self._list(q.get("path", ""))
        if route == "/api/thumb":
            return self._thumb(q.get("path", ""))
        if route == "/api/file":
            return self._file(q.get("path", ""))
        self._json({"error": "not found"}, 404)

    do_HEAD = do_GET

    def do_POST(self):  # noqa: N802
        route = urllib.parse.urlparse(self.path).path
        if not self._authorized():
            return self._json({"error": "pin"}, 401)
        if route != "/api/upload":
            return self._json({"error": "not found"}, 404)
        if not self.server.allow_upload:
            return self._json({"error": "upload disabled"}, 403)
        folder = self._resolve(self._query().get("path", ""))
        name = Path(urllib.parse.unquote(self.headers.get("X-Filename", "upload.bin"))).name
        length = int(self.headers.get("Content-Length") or 0)
        if not folder or not name or not length:
            return self._json({"error": "bad request"}, 400)
        folder = folder / "Загрузки по сети" if folder == self.server.root.resolve() else folder
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / name
        i = 1
        while dst.exists():
            dst = folder / f"{Path(name).stem} ({i}){Path(name).suffix}"
            i += 1
        remaining = length
        with open(dst, "wb") as f:
            while remaining:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        if remaining:
            dst.unlink(missing_ok=True)
            return self._json({"error": "incomplete"}, 400)
        if self.server.on_upload:
            self.server.on_upload(dst)
        self._json({"ok": True, "saved": dst.name})

    def _list(self, rel: str) -> None:
        folder = self._resolve(rel)
        if not folder or not folder.is_dir():
            return self._json({"error": "not found"}, 404)
        folders, files = [], []
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError as e:
            return self._json({"error": str(e)}, 500)
        for p in entries:
            if p.name.startswith("."):
                continue
            if p.is_dir():
                folders.append(p.name)
            elif is_media(p):
                st = p.stat()
                files.append({"name": p.name, "size": st.st_size, "kind": kind_of(p), "mtime": st.st_mtime})
        root = self.server.root.resolve()
        rel_path = "" if folder == root else folder.relative_to(root).as_posix()
        self._json({"path": rel_path,
                    "folders": folders, "files": files})

    def _thumb(self, rel: str) -> None:
        path = self._resolve(rel)
        if not path or not path.is_file():
            return self._json({"error": "not found"}, 404)
        st = path.stat()
        key = hashlib.md5(f"{path}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()
        cache = Settings.app_dir() / "thumbs" / f"{key}.jpg"
        if not cache.exists():
            img = load_preview(path, 400)
            if img is None:
                return self._json({"error": "no preview"}, 415)
            cache.parent.mkdir(exist_ok=True)
            img.save(cache, "JPEG", quality=80)
        self._send(200, cache.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=86400"})

    def _file(self, rel: str) -> None:
        path = self._resolve(rel)
        if not path or not path.is_file():
            return self._json({"error": "not found"}, 404)
        size = path.stat().st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            if a:
                start = int(a)
                end = int(b) if b else end
            elif b:
                start = max(0, size - int(b))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        disp = "attachment" if self._query().get("dl") else "inline"
        self.send_header("Content-Disposition", f"{disp}; filename*=UTF-8''{urllib.parse.quote(path.name)}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (ConnectionError, OSError):
                pass


class ArchiveServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, root: Path, port: int, pin: str = "", allow_upload: bool = True,
                 name: str = "", on_log=None, on_upload=None):
        super().__init__(("0.0.0.0", port), _Handler)
        self.root = Path(root)
        self.pin = pin
        self.allow_upload = allow_upload
        self.name = name or socket.gethostname()
        self.on_log = on_log
        self.on_upload = on_upload
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


# ---- client side: talk to another Home Archive Lab on the network -----------
def _req(base: str, route: str, pin: str = "", params: dict | None = None, timeout: float = 10):
    import urllib.request

    url = f"{base.rstrip('/')}{route}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-PIN": pin} if pin else {})
    return urllib.request.urlopen(req, timeout=timeout)


def remote_info(base: str, timeout: float = 3) -> dict:
    with _req(base, "/api/info", timeout=timeout) as r:
        return json.loads(r.read())


def remote_list(base: str, rel: str = "", pin: str = "") -> dict:
    with _req(base, "/api/list", pin, {"path": rel}) as r:
        return json.loads(r.read())


def remote_thumb(base: str, rel: str, pin: str = "") -> bytes:
    with _req(base, "/api/thumb", pin, {"path": rel}, timeout=30) as r:
        return r.read()


def remote_download(base: str, rel: str, dst: Path, pin: str = "", progress=None) -> Path:
    with _req(base, "/api/file", pin, {"path": rel}, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        dst.parent.mkdir(parents=True, exist_ok=True)
        done = 0
        with open(dst, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
    return dst


def remote_upload(base: str, src: Path, rel: str = "", pin: str = "") -> dict:
    import urllib.request

    url = f"{base.rstrip('/')}/api/upload?" + urllib.parse.urlencode({"path": rel})
    data = Path(src).read_bytes() if Path(src).stat().st_size < 64 << 20 else _FileBody(src)
    headers = {"X-Filename": urllib.parse.quote(Path(src).name), "Content-Length": str(Path(src).stat().st_size),
               "Content-Type": "application/octet-stream"}
    if pin:
        headers["X-PIN"] = pin
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


class _FileBody(io.RawIOBase):
    """Stream big files instead of loading them into memory."""

    def __init__(self, path: Path):
        self._f = open(path, "rb")

    def read(self, n=-1):
        return self._f.read(n)

    def readable(self):
        return True
