"""Dedicated server hosting."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .. import game, maps, master, network
from .widgets import spin_box

LIST_CHECK_MS = 20_000  # give the master server time to take a new server before looking for it

MATCH_MODES = [
    ("Casual: start immediately", False),
    ("Lobby: wait for full teams, then countdown", True),
]


class _Signals(QObject):
    done = Signal(object, object)  # job, result


class _Job(QRunnable):
    """Run fn() off the UI thread and hand its result to done."""

    def __init__(self, fn, on_done):
        super().__init__()
        self.fn, self.on_done = fn, on_done
        self.signals = _Signals()

    def run(self) -> None:
        self.signals.done.emit(self, self.fn())


class HostTab(QWidget):
    status_changed = Signal(str)

    def __init__(self, settings, get_paths, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.get_paths = get_paths  # callable -> GamePaths (raises PathError)
        self.server: game.ServerProcess | None = None

        # --- form -------------------------------------------------------
        self.map = QComboBox()
        self.title = QLineEdit()
        self.title.setMaxLength(60)
        self.password = QLineEdit(placeholderText="none")
        self.mode = QComboBox()
        for label, _ in MATCH_MODES:
            self.mode.addItem(label)
        self.max_players = spin_box(0, 32, "Auto (by map)")
        self.max_spectators = spin_box(0, 16)
        self.bots = spin_box(0, 10, "None")
        self.bot_skill = spin_box(0, 7, "Auto")
        self.goal_score = spin_box(0, 99, "Game default")
        self.time_limit = spin_box(0, 120, "Game default", " min")
        self.golden_goal = QCheckBox("Golden goal on draw")
        self.ranked = QCheckBox("Ranked (needs approval from the Supraball master server)")
        self.port = spin_box(1024, 65535)
        self.query_port = spin_box(1024, 65535)
        self.public = QCheckBox("List on the public server browser")
        self.server_ip = QLineEdit(placeholderText="auto")
        self.server_ip.setToolTip("Public IP to advertise. Leave empty unless players can't reach you.")

        match_box = QGroupBox("Match")
        f = QFormLayout(match_box)
        f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        f.setHorizontalSpacing(16)
        f.addRow("Map", self.map)
        f.addRow("Server name", self.title)
        f.addRow("Password", self.password)
        f.addRow("Mode", self.mode)
        f.addRow("Max players", self.max_players)
        f.addRow("Max spectators", self.max_spectators)
        f.addRow("Bots", self.bots)
        f.addRow("Bot skill", self.bot_skill)
        f.addRow("Goal score", self.goal_score)
        f.addRow("Time limit", self.time_limit)
        f.addRow("", self.golden_goal)
        f.addRow("", self.ranked)

        net_box = QGroupBox("Network")
        n = QFormLayout(net_box)
        n.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        n.setHorizontalSpacing(16)
        n.addRow("Game port (UDP)", self.port)
        n.addRow("Query port (UDP)", self.query_port)
        n.addRow("", self.public)
        n.addRow("Public IP", self.server_ip)
        hint = QLabel("Forward both UDP ports on your router so others can join.", objectName="hint")
        hint.setWordWrap(True)
        n.addRow(hint)
        self.check_btn = QPushButton("Check reachability")
        self.check_btn.setToolTip("Find out whether players on the internet are likely to reach this machine")
        self.check_btn.clicked.connect(self._check_reachability)
        self.reach_label = QLabel(objectName="hint")
        self.reach_label.setWordWrap(True)
        self.reach_label.hide()
        n.addRow(self.check_btn)
        n.addRow(self.reach_label)
        self._jobs: set[_Job] = set()  # keeps signal objects alive until their job reports
        self._public_ip = ""

        # Presets
        self.preset = QComboBox()
        self.preset.setMinimumWidth(160)
        self.preset.activated.connect(self._load_preset)
        save_preset = QPushButton("Save preset…")
        save_preset.clicked.connect(self._save_preset)
        del_preset = QPushButton("Delete")
        del_preset.clicked.connect(self._delete_preset)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset"))
        preset_row.addWidget(self.preset, 1)
        preset_row.addWidget(save_preset)
        preset_row.addWidget(del_preset)

        form_widget = QWidget()
        fl = QVBoxLayout(form_widget)
        fl.addLayout(preset_row)
        fl.addWidget(match_box)
        fl.addWidget(net_box)
        fl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        scroll.setMinimumWidth(400)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # --- run panel --------------------------------------------------
        self.command = QLineEdit(readOnly=True, objectName="command")
        copy_btn = QPushButton("Copy")
        copy_btn.setToolTip("Copy the UDK.exe command line, e.g. to run it on another machine")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.command.text()))
        cmd_row = QHBoxLayout()
        cmd_row.addWidget(self.command, 1)
        cmd_row.addWidget(copy_btn)

        self.start_btn = QPushButton("Start server", objectName="primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Stop server", objectName="danger")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        self.join_btn = QPushButton("Join my server")
        self.join_btn.setEnabled(False)
        self.state_label = QLabel("Not running", objectName="statePill")
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.join_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.state_label)

        self.banner = QLabel(objectName="banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        self._notes: dict[str, tuple[str, str]] = {}  # topic -> (level, text) shown in the banner

        self.log = QPlainTextEdit(readOnly=True, objectName="log")
        self.log.setPlaceholderText("The server's output appears here once you start it.")
        self.log.setMaximumBlockCount(5000)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)

        run_widget = QWidget()
        rl = QVBoxLayout(run_widget)
        rl.addWidget(QLabel("Command line", objectName="heading"))
        rl.addLayout(cmd_row)
        rl.addLayout(btn_row)
        rl.addWidget(self.banner)
        rl.addSpacing(6)
        rl.addWidget(QLabel("Server log", objectName="heading"))
        rl.addWidget(self.log, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(run_widget)
        splitter.setStretchFactor(1, 1)
        QVBoxLayout(self).addWidget(splitter)

        self.poll_timer = QTimer(self, interval=500, timeout=self._poll)

        self.reload_maps()
        self._refresh_presets()
        self.set_config(game.ServerConfig.from_dict(settings.last_server))
        for w in (self.title, self.password, self.server_ip):
            w.textChanged.connect(self._update_command)
        for w in self.findChildren(QSpinBox):
            w.valueChanged.connect(self._update_command)
        for w in self.findChildren(QCheckBox):
            w.toggled.connect(self._update_command)
        self.map.currentIndexChanged.connect(self._update_command)
        self.mode.currentIndexChanged.connect(self._update_command)
        self.public.toggled.connect(self.server_ip.setEnabled)
        self._update_command()

    # --- config <-> form -----------------------------------------------
    def reload_maps(self) -> None:
        current = self.map.currentData()
        try:
            game_dir = self.get_paths().game_dir
        except Exception:
            game_dir = None
        self.map.clear()
        for m in maps.scan_maps(game_dir):
            self.map.addItem(m.label, m.name)
        if current:
            self._select_map(current)

    def _select_map(self, name: str) -> None:
        idx = self.map.findData(name)
        if idx < 0:
            idx = self.map.findData("DB-Pitch")
        self.map.setCurrentIndex(max(idx, 0))

    def config(self) -> game.ServerConfig:
        return game.ServerConfig(
            map=self.map.currentData() or "DB-Pitch",
            title=self.title.text(),
            password=self.password.text(),
            port=self.port.value(),
            query_port=self.query_port.value(),
            max_players=self.max_players.value(),
            max_spectators=self.max_spectators.value(),
            bots=self.bots.value(),
            bot_skill=self.bot_skill.value(),
            goal_score=self.goal_score.value(),
            time_limit=self.time_limit.value(),
            golden_goal=self.golden_goal.isChecked(),
            matchmaking=MATCH_MODES[self.mode.currentIndex()][1],
            ranked=self.ranked.isChecked(),
            public=self.public.isChecked(),
            server_ip=self.server_ip.text().strip(),
        )

    def set_config(self, cfg: game.ServerConfig) -> None:
        self._select_map(cfg.map)
        self.title.setText(cfg.title)
        self.password.setText(cfg.password)
        self.mode.setCurrentIndex(1 if cfg.matchmaking else 0)
        self.max_players.setValue(cfg.max_players)
        self.max_spectators.setValue(cfg.max_spectators)
        self.bots.setValue(cfg.bots)
        self.bot_skill.setValue(cfg.bot_skill)
        self.goal_score.setValue(cfg.goal_score)
        self.time_limit.setValue(cfg.time_limit)
        self.golden_goal.setChecked(cfg.golden_goal)
        self.ranked.setChecked(cfg.ranked)
        self.port.setValue(cfg.port)
        self.query_port.setValue(cfg.query_port)
        self.public.setChecked(cfg.public)
        self.server_ip.setText(cfg.server_ip)
        self.server_ip.setEnabled(cfg.public)

    def _update_command(self) -> None:
        self.command.setText(game.shell_preview(game.build_server_args(self.config())))
        self.command.setCursorPosition(0)

    # --- presets --------------------------------------------------------
    def _refresh_presets(self, select: str = "") -> None:
        self.preset.clear()
        self.preset.addItem("—")
        for name in sorted(self.settings.presets):
            self.preset.addItem(name)
        if select:
            self.preset.setCurrentText(select)

    def _load_preset(self) -> None:
        data = self.settings.presets.get(self.preset.currentText())
        if data:
            self.set_config(game.ServerConfig.from_dict(data))

    def _save_preset(self) -> None:
        current = self.preset.currentText()
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:",
                                        text="" if current == "—" else current)
        if ok and name.strip():
            self.settings.presets[name.strip()] = self.config().to_dict()
            self.settings.save()
            self._refresh_presets(name.strip())

    def _delete_preset(self) -> None:
        name = self.preset.currentText()
        if name in self.settings.presets:
            del self.settings.presets[name]
            self.settings.save()
            self._refresh_presets()

    # --- running --------------------------------------------------------
    def start(self) -> None:
        if self.server and self.server.running:
            return
        try:
            paths = self.get_paths()
        except Exception as e:
            QMessageBox.warning(self, "Can't start server", str(e))
            return
        cfg = self.config()
        if cfg.port == cfg.query_port:
            QMessageBox.warning(self, "Can't start server", "Game port and query port must differ.")
            return
        self.settings.last_server = cfg.to_dict()
        self.settings.save()
        self.log.clear()
        self._notes.clear()
        self._show_notes()
        self.log.appendPlainText(f"$ {game.shell_preview(game.build_server_args(cfg))}")
        self.server = game.ServerProcess(paths, cfg)
        try:
            self.server.start()
        except OSError as e:
            QMessageBox.warning(self, "Can't start server", str(e))
            self.server = None
            return
        self.poll_timer.start()
        if cfg.public:
            self._check_reachability()
            QTimer.singleShot(LIST_CHECK_MS, self._check_listed)
        self._set_running(True, f"Live on port {cfg.port}" + ("" if cfg.public else ", private"))

    def stop(self) -> None:
        if not self.server:
            return
        self.state_label.setText("Stopping…")
        self.stop_btn.setEnabled(False)
        QGuiApplication.processEvents()
        self.server.stop()
        self._poll()

    def _poll(self) -> None:
        if not self.server:
            return
        lines = self.server.poll()
        if lines:
            self.log.appendPlainText("\n".join(lines))
            for line in lines:
                if event := game.parse_server_event(line):
                    self._on_event(event)
        if not self.server.running:
            self.poll_timer.stop()
            code = self.server.proc.returncode if self.server.proc else None
            self.log.appendPlainText(f"--- server exited (code {code}) ---")
            self.server = None
            self._set_running(False, "Not running")

    # --- reachability -------------------------------------------------
    def _run(self, fn, on_done) -> None:
        job = _Job(fn, on_done)
        job.setAutoDelete(False)
        self._jobs.add(job)
        job.signals.done.connect(self._job_done)  # a bound slot, so it runs on the UI thread
        QThreadPool.globalInstance().start(job)

    def _job_done(self, job: _Job, result) -> None:
        self._jobs.discard(job)
        job.on_done(result)

    def _check_reachability(self) -> None:
        cfg = self.config()
        self.check_btn.setEnabled(False)
        self.reach_label.setText("Checking…")
        self.reach_label.show()
        self._run(lambda: network.check(cfg.port, cfg.query_port), self._on_reachability)

    def _on_reachability(self, r: network.Reachability) -> None:
        self.check_btn.setEnabled(True)
        self.reach_label.setText(r.message)
        self._public_ip = r.public
        self.server_ip.setPlaceholderText(f"auto ({r.public})" if r.public else "auto")
        if self.is_running and self.server.cfg.public and r.verdict in ("nat", "cgnat"):
            self._note("reach", "warn", r.message)

    def _check_listed(self) -> None:
        if not (self.is_running and self.server.cfg.public):
            return
        cfg = self.server.cfg
        host, port = self.settings.master_host, self.settings.master_port

        def work():
            try:
                entries = master.fetch_servers(host, port)
            except master.MasterError:
                return None
            ip = cfg.server_ip or self._public_ip
            return network.find_listed(entries, ip, cfg.port) if ip else None

        self._run(work, self._on_listed)

    def _on_listed(self, entry: master.ServerEntry | None) -> None:
        if not self.is_running:
            return
        if entry:
            self._notes.pop("reach", None)  # listed, so the master reached us despite the NAT warning
            self._show_notes()
            self._note("master", "ok", f"Your server is on the public list as {entry.address}.")
        elif "master" not in self._notes:
            self._note("master", "warn", "Your server isn't on the public list yet.")

    def _on_event(self, event: game.ServerEvent) -> None:
        cfg = self.server.cfg
        if event.kind == "port_in_use":
            self._note("port", "warn", game.explain(event, cfg))
            return
        if not cfg.public:
            return  # private servers point the master client at 127.0.0.1 on purpose
        listed = event.kind == "listed"
        self._note("master", "ok" if listed else "warn", game.explain(event, cfg))
        self.state_label.setText(f"Live on port {cfg.port}, " + ("listed" if listed else "not listed"))

    def _note(self, topic: str, level: str, text: str) -> None:
        if self._notes.get(topic) != (level, text):  # the master is re-contacted every few seconds
            self._notes[topic] = (level, text)
            self._show_notes()

    def _show_notes(self) -> None:
        notes = list(self._notes.values())
        self.banner.setVisible(bool(notes))
        self.banner.setText("\n\n".join(text for _, text in notes))
        self.banner.setProperty("level", "warn" if any(level == "warn" for level, _ in notes) else "ok")
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)

    def _set_running(self, running: bool, text: str) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.join_btn.setEnabled(running)
        self.state_label.setText(text)
        self.state_label.setProperty("live", running)
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
        self.status_changed.emit(f"Your server: {text.lower()}")

    @property
    def is_running(self) -> bool:
        return bool(self.server and self.server.running)
