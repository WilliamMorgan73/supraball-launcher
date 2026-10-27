"""Main window: server browser + hosting tabs, settings, and launching the game."""

from __future__ import annotations

import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import game, official, paths, steam_config
from ..config import Settings
from ..master import MASTER_HOST, MASTER_PORT
from .browser_tab import BrowserTab
from .costume_tab import CostumeTab
from .game_settings_tab import GameSettingsTab
from .host_tab import HostTab
from .widgets import PitchBackground, Scoreboard


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(620)
        self.game_dir = QLineEdit(settings.game_dir, placeholderText="auto-detect")
        self.proton_dir = QLineEdit(settings.proton_dir, placeholderText="auto-detect")
        self.master_host = QLineEdit(settings.master_host)
        self.master_port = QSpinBox()
        self.master_port.lineEdit().setTextMargins(6, 0, 0, 0)
        self.master_port.setRange(1, 65535)
        self.master_port.setValue(settings.master_port)
        self.detected = QLabel(objectName="hint")
        self.detected.setWordWrap(True)

        form = QFormLayout(self)
        form.addRow("Supraball folder", self._with_browse(self.game_dir))
        form.addRow("Proton folder", self._with_browse(self.proton_dir))
        form.addRow("Master server", self.master_host)
        form.addRow("Master port", self.master_port)
        reset = QPushButton("Reset master to default")
        reset.clicked.connect(lambda: (self.master_host.setText(MASTER_HOST), self.master_port.setValue(MASTER_PORT)))
        form.addRow("", reset)
        form.addRow("Detected", self.detected)

        self.steam_status = QLabel(objectName="hint")
        self.steam_status.setWordWrap(True)
        self.steam_btn = QPushButton()
        self.steam_btn.clicked.connect(self._toggle_steam_default)
        steam_row = QWidget()
        sr = QVBoxLayout(steam_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(self.steam_status)
        sr.addWidget(self.steam_btn)
        form.addRow("Steam Play button", steam_row)
        self._show_steam_status()

        self.official_status = QLabel(objectName="hint")
        self.official_status.setWordWrap(True)
        self.unlock_btn = QPushButton("Skip the tutorial there")
        self.unlock_btn.setToolTip("Marks the tutorial as completed for the official launcher on this computer")
        self.unlock_btn.clicked.connect(self._unlock_tutorial)
        open_btn = QPushButton("Open official launcher")
        open_btn.setToolTip("For things this launcher doesn't do, like opening chests or matchmaking")
        open_btn.clicked.connect(self._open_official)
        official_row = QWidget()
        orow = QVBoxLayout(official_row)
        orow.setContentsMargins(0, 0, 0, 0)
        orow.addWidget(self.official_status)
        buttons_row = QHBoxLayout()
        buttons_row.addWidget(self.unlock_btn)
        buttons_row.addWidget(open_btn)
        orow.addLayout(buttons_row)
        form.addRow("Official launcher", official_row)
        self._show_official_status()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.game_dir.textChanged.connect(self._show_detected)
        self.proton_dir.textChanged.connect(self._show_detected)
        self._show_detected()

    def _with_browse(self, edit: QLineEdit) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())) and edit.setText(d))
        row.addWidget(btn)
        return w

    def _show_detected(self) -> None:
        try:
            p = paths.detect(self.game_dir.text().strip(), self.proton_dir.text().strip())
        except paths.PathError as e:
            self.detected.setText(str(e))
            return
        self.detected.setText(
            f"Game: {p.game_dir}\nPrefix: {p.compat_data}\nProton: {p.proton_dir}\n"
            f"Runtime: {p.runtime_dir or 'none (running Proton directly)'}"
        )

    def _is_steam_default(self) -> bool:
        try:
            return steam_config.current() == steam_config.launch_option()
        except (OSError, paths.PathError):
            return False

    def _show_steam_status(self) -> None:
        if self._is_steam_default():
            self.steam_status.setText("Opens this launcher.")
            self.steam_btn.setText("Use the official launcher again")
        else:
            self.steam_status.setText("Opens the official launcher.")
            self.steam_btn.setText("Make this the launcher Steam opens")

    def _toggle_steam_default(self) -> None:
        value = None if self._is_steam_default() else steam_config.launch_option()
        try:
            steam_config.apply(value)
        except (steam_config.SteamConfigError, OSError, paths.PathError) as e:
            QMessageBox.information(
                self, "Couldn't change Steam's launch options",
                f"{e}\n\nOr set it by hand: in Steam, right-click Supraball > Properties > General > "
                f"Launch Options, and enter:\n\n{steam_config.launch_option()}",
            )
            return
        self._show_steam_status()
        QMessageBox.information(self, "Steam updated", "Done. Start Steam again and press Play on Supraball.")

    def _paths(self) -> paths.GamePaths:
        return paths.detect(self.game_dir.text().strip(), self.proton_dir.text().strip())

    def _show_official_status(self) -> None:
        try:
            done = official.tutorial_unlocked(self._paths())
        except paths.PathError:
            done = False
        self.official_status.setText(
            "Tutorial marked as done on this computer." if done
            else "Asks you to finish the tutorial before playing online.")
        self.unlock_btn.setEnabled(not done)

    def _unlock_tutorial(self) -> None:
        try:
            p = self._paths()
        except paths.PathError as e:
            QMessageBox.warning(self, "Couldn't skip the tutorial", str(e))
            return
        self.unlock_btn.setEnabled(False)
        self.official_status.setText("Marking the tutorial as done…")
        result: list[Exception | None] = []

        def work() -> None:
            try:
                official.unlock_tutorial(p)
                result.append(None)
            except Exception as e:  # reported in the dialog below
                result.append(e)

        threading.Thread(target=work, daemon=True).start()
        timer = QTimer(self, interval=200)

        def check() -> None:
            if not result:
                return
            timer.stop()
            self._show_official_status()
            if result[0] is not None:
                QMessageBox.warning(self, "Couldn't skip the tutorial", str(result[0]))
                self.unlock_btn.setEnabled(True)

        timer.timeout.connect(check)
        timer.start()

    def _open_official(self) -> None:
        try:
            official.open_official(self._paths())
        except (paths.PathError, OSError) as e:
            QMessageBox.warning(self, "Couldn't open the official launcher", str(e))

    def apply(self, settings: Settings) -> None:
        settings.game_dir = self.game_dir.text().strip()
        settings.proton_dir = self.proton_dir.text().strip()
        settings.master_host = self.master_host.text().strip() or MASTER_HOST
        settings.master_port = self.master_port.value()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Supraball Launcher")
        self.resize(1180, 760)
        self.setMinimumSize(920, 600)
        self.settings = Settings.load()
        self._force_quit = False  # set by Ctrl+C: stop the server without asking
        self._busy: set[str] = set()  # tabs currently waiting on the network; the ball hops while any are

        self.scoreboard = Scoreboard()
        self.scoreboard.play_btn.clicked.connect(self.play)
        self.scoreboard.settings_btn.clicked.connect(self.open_settings)

        self.browser = BrowserTab(self.settings)
        self.browser.join_requested.connect(self.join)
        self.browser.counts_changed.connect(self.scoreboard.set_counts)
        self.browser.busy_changed.connect(lambda b: self._set_busy("browser", b))
        self.host = HostTab(self.settings, self.paths)
        self.host.status_changed.connect(self.statusBar().showMessage)
        self.host.join_btn.clicked.connect(lambda: self.join("127.0.0.1", self.host.port.value(), self.host.password.text()))

        self.costume = CostumeTab(self.settings, self.paths)
        self.costume.busy_changed.connect(lambda b: self._set_busy("costume", b))

        self.game_settings = GameSettingsTab(self.paths)

        tabs = QTabWidget()
        tabs.addTab(self.browser, "Join a game")
        tabs.addTab(self.host, "Host a game")
        tabs.addTab(self.costume, "Costume")
        tabs.addTab(self.game_settings, "Game settings")
        for page in (self.browser, self.host, self.costume, self.game_settings):
            page.layout().setContentsMargins(16, 4, 16, 14)

        pitch = PitchBackground()
        pl = QVBoxLayout(pitch)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(tabs)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.scoreboard)
        cl.addWidget(pitch, 1)
        self.setCentralWidget(central)

        try:
            p = self.paths()
            self.statusBar().showMessage(f"Found Supraball in {p.game_dir}, running it with {p.proton_dir.name}.")
        except paths.PathError as e:
            self.statusBar().showMessage(str(e))

    def paths(self) -> paths.GamePaths:
        return paths.detect(self.settings.game_dir, self.settings.proton_dir)

    def _launch(self, udk_args: list[str], what: str) -> None:
        try:
            game.launch_detached(self.paths(), udk_args)
        except (paths.PathError, OSError) as e:
            QMessageBox.warning(self, "Can't launch Supraball", str(e))
            return
        self.statusBar().showMessage(f"{what}. Keep Steam running while you play.", 10_000)

    def play(self) -> None:
        self._launch([], "Starting Supraball")

    def join(self, host: str, port: int, password: str) -> None:
        self._launch(game.build_join_args(host, port, password), f"Joining {host}:{port}")

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            dlg.apply(self.settings)
            self.settings.save()
            self.host.reload_maps()
            self.browser.refresh()

    def _set_busy(self, source: str, busy: bool) -> None:
        if busy:
            self._busy.add(source)
        else:
            self._busy.discard(source)
        self.scoreboard.set_busy(bool(self._busy))

    def quit_from_signal(self) -> None:
        self._force_quit = True
        self.close()

    def closeEvent(self, event) -> None:
        if self.host.is_running and self._force_quit:
            self.host.stop()
        elif self.host.is_running:
            answer = QMessageBox.question(
                self, "Server running", "A dedicated server is still running. Stop it and quit?",
                QMessageBox.Yes | QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.host.stop()
        self.costume.shutdown()
        super().closeEvent(event)
