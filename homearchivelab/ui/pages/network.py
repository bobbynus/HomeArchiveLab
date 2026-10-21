"""Network page: share the library on the LAN (web gallery + QR) and browse other Home Archive Lab PCs."""
from __future__ import annotations

import io
import secrets
import webbrowser
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QSpinBox, QSplitter,
                               QVBoxLayout, QWidget)

from ...core.settings import Settings
from ...net import server as net
from ...net.discovery import Discovery
from .. import icons, theme
from ..widgets import Card, FolderPicker, Page, ProgressRow, button, label, placeholder, run_task


def qr_pixmap(text: str, size: int = 180) -> QPixmap | None:
    try:
        import qrcode

        q = qrcode.QRCode(border=2, box_size=8)
        q.add_data(text)
        img = q.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        qi = QImage.fromData(buf.getvalue())
        return QPixmap.fromImage(qi).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        return None


class NetworkPage(Page):
    log_sig = Signal(str)

    def __init__(self, state):
        super().__init__("Сеть", "Делитесь архивом с телефоном и другими ПК в локальной сети", state)
        self.server: net.ArchiveServer | None = None
        self.discovery = Discovery(Settings.get("device_name"))
        self.discovery.start()

        split = QSplitter()
        # ---- server side
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        srv = Card("Мой сервер", "Откройте адрес в браузере телефона или отсканируйте QR-код. "
                                 "Можно смотреть, скачивать и загружать фото с телефона.")
        f = QFormLayout()
        self.folder = FolderPicker("Папка для доступа", state.library)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(Settings.get("lan_port")))
        self.port.setButtonSymbols(QSpinBox.NoButtons)
        pin_row = QHBoxLayout()
        self.pin = QLineEdit(Settings.get("lan_pin"))
        self.pin.setPlaceholderText("без PIN — доступ всем в сети")
        b_gen = button("Создать", tip="Сгенерировать PIN")
        b_gen.clicked.connect(lambda: self.pin.setText(f"{secrets.randbelow(10 ** 6):06d}"))
        pin_row.addWidget(self.pin, 1)
        pin_row.addWidget(b_gen)
        self.upload = QCheckBox("Разрешить загрузку файлов на этот ПК")
        self.upload.setChecked(bool(Settings.get("lan_allow_upload")))
        f.addRow("Папка", self.folder)
        f.addRow("Порт", self.port)
        f.addRow("PIN", pin_row)
        f.addRow("", self.upload)
        srv.lay.addLayout(f)
        row = QHBoxLayout()
        self.b_srv = button("Запустить сервер", "wifi", "Primary")
        self.b_srv.clicked.connect(self.toggle_server)
        self.b_web = button("Открыть в браузере", "open")
        self.b_web.clicked.connect(lambda: self.urls and webbrowser.open(self.urls[0]))
        self.b_web.setEnabled(False)
        row.addWidget(self.b_srv)
        row.addWidget(self.b_web)
        row.addStretch()
        srv.lay.addLayout(row)
        info = QHBoxLayout()
        self.qr = QLabel()
        self.qr.setFixedSize(190, 190)
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setStyleSheet(f"background:{theme.BG};border-radius:12px;")
        self.addr = label("Сервер выключен", "Muted", wrap=True)
        self.addr.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.addWidget(self.qr)
        info.addWidget(self.addr, 1)
        srv.lay.addLayout(info)
        ll.addWidget(srv)
        logc = Card("Журнал")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        logc.lay.addWidget(self.log)
        ll.addWidget(logc, 1)
        split.addWidget(left)

        # ---- client side
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        peers = Card("Устройства в сети", "Другие компьютеры с Home Archive Lab появляются автоматически.")
        self.peers = QListWidget()
        self.peers.setMaximumHeight(130)
        peers.lay.addWidget(self.peers)
        pr = QHBoxLayout()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("или адрес вручную: 192.168.1.20:8765")
        b_conn = button("Подключиться", "network")
        b_conn.clicked.connect(self._connect_manual)
        pr.addWidget(self.manual, 1)
        pr.addWidget(b_conn)
        peers.lay.addLayout(pr)
        rl.addWidget(peers)

        rem = Card("Удалённый архив")
        nav = QHBoxLayout()
        self.b_up = button("↑ Вверх")
        self.b_up.clicked.connect(self._go_up)
        self.remote_path = label("Не подключено", "Muted")
        nav.addWidget(self.b_up)
        nav.addWidget(self.remote_path, 1)
        rem.lay.addLayout(nav)
        self.remote = QListWidget()
        self.remote.setViewMode(QListWidget.IconMode)
        self.remote.setIconSize(QSize(110, 110))
        self.remote.setGridSize(QSize(130, 150))
        self.remote.setResizeMode(QListWidget.Adjust)
        self.remote.setMovement(QListWidget.Static)
        self.remote.setSelectionMode(QListWidget.ExtendedSelection)
        self.remote.setWordWrap(True)
        self.remote.itemDoubleClicked.connect(self._open_remote)
        rem.lay.addWidget(self.remote, 1)
        ar = QHBoxLayout()
        self.b_dl = button("Скачать выбранное", "download", "Primary")
        self.b_send = button("Отправить файлы туда", "upload")
        self.b_dl.clicked.connect(self.download)
        self.b_send.clicked.connect(self.send_files)
        ar.addWidget(self.b_dl)
        ar.addWidget(self.b_send)
        ar.addStretch()
        rem.lay.addLayout(ar)
        self.progress = ProgressRow()
        rem.lay.addWidget(self.progress)
        rl.addWidget(rem, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        self.body.addWidget(split, 1)

        self.urls: list[str] = []
        self.base: str | None = None
        self.base_pin = ""
        self.rel = ""
        self.peers.itemDoubleClicked.connect(self._connect_peer)
        self.peers.itemClicked.connect(self._connect_peer)
        self._peer_timer = QTimer(self)
        self._peer_timer.timeout.connect(self._refresh_peers)
        self._peer_timer.start(2500)
        self.discovery.probe()
        state.library_changed.connect(lambda p: self.folder.value() or self.folder.set_value(p))
        self.log_sig.connect(self._log)

    # ---- server
    def toggle_server(self):
        if self.server:
            self.server.stop()
            self.server = None
            self.discovery.port = None
            self.b_srv.setText("Запустить сервер")
            self.addr.setText("Сервер выключен")
            self.qr.clear()
            self.b_web.setEnabled(False)
            self._log("Сервер остановлен")
            return
        folder = self.folder.value()
        if not folder or not Path(folder).is_dir():
            return QMessageBox.warning(self, "Сервер", "Выберите существующую папку.")
        Settings.set("lan_port", self.port.value())
        Settings.set("lan_pin", self.pin.text().strip())
        Settings.set("lan_allow_upload", self.upload.isChecked())
        try:
            self.server = net.ArchiveServer(Path(folder), self.port.value(), self.pin.text().strip(),
                                            self.upload.isChecked(), Settings.get("device_name"),
                                            on_log=self._log_threadsafe,
                                            on_upload=lambda p: self._log_threadsafe(f"Загружен файл: {p.name}"))
        except OSError as e:
            return QMessageBox.critical(self, "Сервер", f"Не удалось открыть порт {self.port.value()}: {e}")
        self.server.start()
        self.discovery.port = self.port.value()
        self.discovery.name = Settings.get("device_name")
        ips = net.local_ips() or ["127.0.0.1"]
        self.urls = [f"http://{ip}:{self.port.value()}" for ip in ips]
        pin = self.pin.text().strip()
        self.addr.setText("Сервер работает:\n" + "\n".join(self.urls) + (f"\n\nPIN: {pin}" if pin else "") +
                          "\n\nПри первом запуске Windows может спросить разрешение для брандмауэра — разрешите "
                          "доступ в частных сетях.")
        pm = qr_pixmap(self.urls[0])
        if pm:
            self.qr.setPixmap(pm)
        self.b_srv.setText("Остановить сервер")
        self.b_web.setEnabled(True)
        self._log(f"Сервер запущен: {', '.join(self.urls)}")

    def _log_threadsafe(self, text: str):
        # Called from server threads: a queued signal hops to the GUI thread.
        self.log_sig.emit(text)

    def _log(self, text: str):
        from datetime import datetime

        self.log.appendPlainText(f"[{datetime.now():%H:%M:%S}] {text}")

    # ---- peers
    def _refresh_peers(self):
        known = {self.peers.item(i).data(Qt.UserRole) for i in range(self.peers.count())}
        active = {f"{p['ip']}:{p['port']}": p for p in self.discovery.active_peers()}
        if set(active) == known and self.peers.count():
            return
        self.peers.clear()
        for key, p in active.items():
            it = QListWidgetItem(icons.icon("network", theme.ACCENT2), f"{p['name']}   ·   {key}")
            it.setData(Qt.UserRole, key)
            self.peers.addItem(it)
        if not active:
            it = QListWidgetItem("Поиск устройств… (на другом ПК запустите сервер)")
            it.setFlags(Qt.NoItemFlags)
            self.peers.addItem(it)

    def _connect_peer(self, item):
        key = item.data(Qt.UserRole)
        if key:
            self.connect_to(f"http://{key}")

    def _connect_manual(self):
        addr = self.manual.text().strip()
        if not addr:
            return
        if not addr.startswith("http"):
            addr = "http://" + addr
        if addr.count(":") < 2:
            addr += ":8765"
        self.connect_to(addr)

    def connect_to(self, base: str):
        def work(report, cancelled):
            return net.remote_info(base)

        def done(info):
            self.base = base
            self.base_pin = ""
            if info.get("auth"):
                pin, ok = QInputDialog.getText(self, "PIN", f"Устройство «{info.get('name')}» защищено PIN-кодом:")
                if not ok:
                    return
                self.base_pin = pin.strip()
            self._log(f"Подключено к {info.get('name')} ({base})")
            self.browse("")

        run_task(work, done, on_error=lambda m: QMessageBox.warning(self, "Подключение", f"Не удалось подключиться: {m}"))

    # ---- remote browsing
    def browse(self, rel: str):
        base, pin = self.base, self.base_pin

        def work(report, cancelled):
            return net.remote_list(base, rel, pin)

        def done(data):
            self.rel = data.get("path", "")
            self.remote_path.setText(f"{base} / {self.rel}")
            self.remote.clear()
            for name in data["folders"]:
                it = QListWidgetItem(icons.icon("folder", theme.ACCENT), name)
                it.setData(Qt.UserRole, ("dir", name))
                self.remote.addItem(it)
            for f in data["files"]:
                it = QListWidgetItem(name_short(f["name"]))
                it.setToolTip(f["name"])
                it.setData(Qt.UserRole, ("file", f["name"]))
                it.setIcon(placeholder(f["kind"], 110))
                self.remote.addItem(it)
            self._load_thumbs([f["name"] for f in data["files"]])

        def err(m):
            if "401" in m:
                pin, ok = QInputDialog.getText(self, "PIN", "Неверный PIN. Попробуйте ещё раз:")
                if ok:
                    self.base_pin = pin.strip()
                    self.browse(rel)
                return
            QMessageBox.warning(self, "Сеть", m)

        run_task(work, done, on_error=err)

    def _load_thumbs(self, names):
        base, pin, rel = self.base, self.base_pin, self.rel

        def work(report, cancelled):
            for i, n in enumerate(names):
                if cancelled() or self.rel != rel:
                    return
                try:
                    data = net.remote_thumb(base, f"{rel}/{n}" if rel else n, pin)
                    report(i, n + "\x00" + data.hex())
                except Exception:
                    pass

        def on_thumb(_i, payload):
            name, _, hexdata = payload.partition("\x00")
            for k in range(self.remote.count()):
                it = self.remote.item(k)
                if it.data(Qt.UserRole) == ("file", name):
                    it.setIcon(QPixmap.fromImage(QImage.fromData(bytes.fromhex(hexdata))))
                    break

        if getattr(self, "_thumb_task", None):
            self._thumb_task.cancel()
        self._thumb_task = run_task(work, on_progress=on_thumb)

    def _open_remote(self, item):
        kind, name = item.data(Qt.UserRole)
        if kind == "dir":
            self.browse(f"{self.rel}/{name}" if self.rel else name)
        else:
            from urllib.parse import urlencode

            q = {"path": f"{self.rel}/{name}" if self.rel else name}
            if self.base_pin:
                q["pin"] = self.base_pin
            webbrowser.open(f"{self.base}/api/file?{urlencode(q)}")

    def _go_up(self):
        if self.base:
            self.browse(self.rel.rsplit("/", 1)[0] if "/" in self.rel else "")

    def download(self):
        if not self.base:
            return
        items = [self.remote.item(i).data(Qt.UserRole) for i in range(self.remote.count())
                 if self.remote.item(i).isSelected()]
        names = [n for k, n in items if k == "file"]
        if not names:
            return QMessageBox.information(self, "Скачивание", "Выделите файлы в удалённом архиве.")
        dst = QFileDialog.getExistingDirectory(self, "Куда сохранить", self.state.library or "")
        if not dst:
            return
        base, pin, rel = self.base, self.base_pin, self.rel
        self.progress.start("Скачивание…")
        n = len(names)

        def work(report, cancelled):
            for i, name in enumerate(names):
                if cancelled():
                    break
                target = Path(dst) / name
                k = 1
                while target.exists():
                    target = Path(dst) / f"{Path(name).stem} ({k}){Path(name).suffix}"
                    k += 1
                net.remote_download(base, f"{rel}/{name}" if rel else name, target, pin,
                                    lambda f, i=i: report((i + f) / n, f"{i + 1}/{n}  {name}"))
            return n

        run_task(work, lambda c: (self.progress.finish(f"Скачано: {c}"), self.state.toast.emit(f"Скачано файлов: {c}")),
                 self.progress.update, lambda m: (self.progress.finish("Ошибка"), QMessageBox.warning(self, "Ошибка", m)))

    def send_files(self):
        if not self.base:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Отправить файлы", self.state.library or "")
        if not files:
            return
        base, pin, rel = self.base, self.base_pin, self.rel
        self.progress.start("Отправка…")
        n = len(files)

        def work(report, cancelled):
            for i, f in enumerate(files):
                if cancelled():
                    break
                report(i / n, f"{i + 1}/{n}  {Path(f).name}")
                net.remote_upload(base, Path(f), rel, pin)
            return n

        def done(c):
            self.progress.finish(f"Отправлено: {c}")
            self.browse(self.rel)

        run_task(work, done, self.progress.update,
                 lambda m: (self.progress.finish("Ошибка"), QMessageBox.warning(self, "Ошибка", m)))

    def shutdown(self):
        if self.server:
            self.server.stop()
        self.discovery.stop()


def name_short(name: str, n: int = 18) -> str:
    return name if len(name) <= n else name[: n - 6] + "…" + name[-5:]
