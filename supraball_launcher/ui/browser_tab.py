"""Internet server browser."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QRunnable, QSortFilterProxyModel, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QPushButton, QTableView, QVBoxLayout, QWidget,
)

from .. import maps, master
from . import theme
from .widgets import PlayersDelegate

COLUMNS = ["", "Name", "Map", "Players", "Type", "Ping", "Address"]
COL_LOCK, COL_NAME, COL_MAP, COL_PLAYERS, COL_TYPE, COL_PING, COL_ADDR = range(len(COLUMNS))
ENTRY_ROLE = Qt.UserRole + 1
SORT_ROLE = Qt.UserRole + 2
REFRESH_MS = 60_000


class _Signals(QObject):
    listed = Signal(int, list)  # generation, servers
    failed = Signal(int, str)
    pinged = Signal(int, str, object)  # generation, address, ping ms | None
    players = Signal(int, str, object)  # generation, address, list[PlayerInfo] | None


class _FetchJob(QRunnable):
    def __init__(self, gen: int, host: str, port: int, signals: _Signals):
        super().__init__()
        self.gen, self.host, self.port, self.signals = gen, host, port, signals

    def run(self) -> None:
        try:
            servers = master.fetch_servers(self.host, self.port)
        except master.MasterError as e:
            self.signals.failed.emit(self.gen, str(e))
            return
        self.signals.listed.emit(self.gen, servers)
        with ThreadPoolExecutor(max_workers=16) as pool:
            populated = [s for s in servers if s.players]
            names = pool.map(lambda s: master.a2s_players(s.ip, s.query_port), populated)
            for s, ping in zip(servers, pool.map(lambda s: master.a2s_ping(s.ip, s.query_port), servers)):
                self.signals.pinged.emit(self.gen, s.address, ping)
            for s, players in zip(populated, names):
                self.signals.players.emit(self.gen, s.address, players)


def players_tooltip(s: master.ServerEntry, players: list[master.PlayerInfo] | None = None) -> str:
    lines = [f"{s.players}/{s.max_players} players"]
    if s.max_spectators:
        lines[0] += f", {s.spectators}/{s.max_spectators} spectators"
    for p in players or []:
        name = p.name or "(joining)"
        lines.append(f"{name}  ·  {p.score} pts  ·  {int(p.seconds // 60)} min")
    return "\n".join(lines)


class ServerFilter(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.text = ""
        self.hide_empty = False
        self.hide_full = False
        self.hide_locked = False

    def filterAcceptsRow(self, row: int, parent) -> bool:
        s: master.ServerEntry = self.sourceModel().index(row, 0, parent).data(ENTRY_ROLE)
        if s is None:
            return True
        if self.text and self.text not in f"{s.name} {s.map} {s.type} {s.address}".lower():
            return False
        if self.hide_empty and s.players == 0:
            return False
        if self.hide_full and s.max_players and s.players >= s.max_players:
            return False
        return not (self.hide_locked and s.passworded)


class BrowserTab(QWidget):
    join_requested = Signal(str, int, str)  # host, port, password
    counts_changed = Signal(int, int)  # servers, players
    busy_changed = Signal(bool)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.generation = 0
        self.signals = _Signals()
        self.signals.listed.connect(self._on_listed)
        self.signals.failed.connect(self._on_failed)
        self.signals.pinged.connect(self._on_pinged)
        self.signals.players.connect(self._on_players)
        self.rows_by_addr: dict[str, int] = {}

        self.loaded = False
        self.error = ""
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        self.search = QLineEdit(placeholderText="Search name, map, address…")
        self.search.setClearButtonEnabled(True)
        self.hide_empty = QCheckBox("Hide empty")
        self.hide_full = QCheckBox("Hide full")
        self.hide_locked = QCheckBox("Hide passworded")
        self.auto = QCheckBox("Auto-refresh")
        self.auto.setChecked(settings.auto_refresh)
        for w in (self.search,):
            w.textChanged.connect(self._apply_filter)
        for cb in (self.hide_empty, self.hide_full, self.hide_locked):
            cb.toggled.connect(self._apply_filter)
        self.auto.toggled.connect(self._on_auto_toggled)

        top = QHBoxLayout()
        top.addWidget(self.refresh_btn)
        top.addWidget(self.search, 1)
        for w in (self.hide_empty, self.hide_full, self.hide_locked, self.auto):
            top.addWidget(w)

        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.proxy = ServerFilter()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setSortCaseSensitivity(Qt.CaseInsensitive)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_PLAYERS, Qt.DescendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(COL_LOCK, QHeaderView.Fixed)
        header.resizeSection(COL_LOCK, 34)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setItemDelegateForColumn(COL_PLAYERS, PlayersDelegate(ENTRY_ROLE, self.table))
        self.empty = QLabel(self.table.viewport(), objectName="emptyState")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.proxy.rowsInserted.connect(self._update_empty)
        self.proxy.rowsRemoved.connect(self._update_empty)
        self.proxy.modelReset.connect(self._update_empty)
        self.proxy.layoutChanged.connect(self._update_empty)
        self.table.doubleClicked.connect(lambda _: self.join_selected())

        self.status = QLabel(objectName="hint")
        self.join_btn = QPushButton("Join", objectName="primary")
        self.join_btn.setDefault(True)
        self.join_btn.clicked.connect(self.join_selected)
        self.direct_btn = QPushButton("Connect to IP…")
        self.direct_btn.clicked.connect(self.direct_connect)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.direct_btn)
        bottom.addWidget(self.join_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)

        self.timer = QTimer(self, interval=REFRESH_MS, timeout=self.refresh)
        if self.auto.isChecked():
            self.timer.start()
        QTimer.singleShot(0, self.refresh)

    # --- fetching -------------------------------------------------------
    def refresh(self) -> None:
        self.generation += 1
        self.refresh_btn.setEnabled(False)
        self.busy_changed.emit(True)
        self.status.setText("Looking for games…")
        QThreadPool.globalInstance().start(
            _FetchJob(self.generation, self.settings.master_host, self.settings.master_port, self.signals)
        )

    def _on_listed(self, gen: int, servers: list) -> None:
        if gen != self.generation:
            return
        self.refresh_btn.setEnabled(True)
        self.busy_changed.emit(False)
        self.loaded = True
        self.error = ""
        selected = self._selected_entry()
        self.table.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        self.rows_by_addr.clear()
        for s in servers:
            self.rows_by_addr[s.address] = self.model.rowCount()
            self.model.appendRow(self._make_row(s))
        self.table.setSortingEnabled(True)
        players = sum(s.players for s in servers)
        self.counts_changed.emit(len(servers), players)
        self.status.setText(f"Updated the list from {self.settings.master_host}.")
        self.status.setToolTip("")
        self._update_empty()
        if selected:
            self._select_address(selected.address)

    def _on_failed(self, gen: int, message: str) -> None:
        if gen == self.generation:
            self.refresh_btn.setEnabled(True)
            self.busy_changed.emit(False)
            self.loaded = True
            self.error = (f"Can't reach the master server at {self.settings.master_host}:{self.settings.master_port}. "
                          "Check your connection, then press Refresh.")
            self.status.setText(self.error)
            self.status.setToolTip(message)
            self._update_empty()

    def _on_pinged(self, gen: int, address: str, ping) -> None:
        row = self.rows_by_addr.get(address)
        if gen != self.generation or row is None:
            return
        item = self.model.item(row, COL_PING)
        item.setText("no reply" if ping is None else f"{ping} ms")
        item.setData(10_000 if ping is None else ping, SORT_ROLE)
        item.setForeground(theme.ping_color(ping))
        self.model.item(row, 0).data(ENTRY_ROLE).ping = ping

    def _on_players(self, gen: int, address: str, players) -> None:
        row = self.rows_by_addr.get(address)
        if gen != self.generation or row is None or not players:
            return
        s = self.model.item(row, 0).data(ENTRY_ROLE)
        self.model.item(row, COL_PLAYERS).setToolTip(players_tooltip(s, players))

    def _make_row(self, s: master.ServerEntry) -> list[QStandardItem]:
        def item(text: str, sort=None) -> QStandardItem:
            it = QStandardItem(text)
            it.setData(text if sort is None else sort, SORT_ROLE)
            return it

        players = f"{s.players}/{s.max_players}"
        if s.spectators:
            players += f" (+{s.spectators})"
        server_type = s.type + (" · Ranked" if s.ranked else "")
        row = [
            item("🔒" if s.passworded else "", int(s.passworded)),
            item(s.name),
            item(maps.display_name(s.map)),
            item(players, s.players * 100 + s.max_players),
            item(server_type),
            item("…", 9_999),  # filled in by _on_pinged
            item(s.address),
        ]
        row[COL_PING].setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row[COL_PING].setForeground(QColor(theme.MUTED))
        row[COL_ADDR].setForeground(QColor(theme.CHALK_DIM))
        if s.passworded:
            row[COL_LOCK].setToolTip("Needs a password")
        row[COL_PLAYERS].setToolTip(players_tooltip(s))
        row[COL_NAME].setToolTip(f"{s.name}\nVersion {s.version}\nTime limit {s.timelimit} min")
        row[0].setData(s, ENTRY_ROLE)
        return row

    def _update_empty(self) -> None:
        if not self.loaded:
            text = ""
        elif self.error and self.model.rowCount() == 0:
            text = self.error
        elif self.model.rowCount() == 0:
            text = "No servers are online right now.\nStart one from Host a game."
        elif self.proxy.rowCount() == 0:
            text = "No servers match your filters."
        else:
            text = ""
        self.empty.setText(text)
        self.empty.setVisible(bool(text))
        self.empty.setGeometry(self.table.viewport().rect().adjusted(40, 0, -40, 0))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_empty()

    # --- filtering & selection -----------------------------------------
    def _apply_filter(self) -> None:
        self.proxy.text = self.search.text().strip().lower()
        self.proxy.hide_empty = self.hide_empty.isChecked()
        self.proxy.hide_full = self.hide_full.isChecked()
        self.proxy.hide_locked = self.hide_locked.isChecked()
        self.proxy.invalidateFilter()
        self._update_empty()

    def _on_auto_toggled(self, on: bool) -> None:
        self.settings.auto_refresh = on
        self.settings.save()
        self.timer.start() if on else self.timer.stop()

    def _selected_entry(self) -> master.ServerEntry | None:
        rows = self.table.selectionModel().selectedRows()
        return self.proxy.index(rows[0].row(), 0).data(ENTRY_ROLE) if rows else None

    def _select_address(self, address: str) -> None:
        row = self.rows_by_addr.get(address)
        if row is not None:
            idx = self.proxy.mapFromSource(self.model.index(row, 0))
            if idx.isValid():
                self.table.selectRow(idx.row())

    # --- joining --------------------------------------------------------
    def join_selected(self) -> None:
        s = self._selected_entry()
        if not s:
            self.status.setText("Pick a server from the list first.")
            return
        password = ""
        if s.passworded:
            password, ok = QInputDialog.getText(self, "Password", f"Password for {s.name}:", QLineEdit.Password)
            if not ok:
                return
        self.join_requested.emit(s.ip, s.port, password)

    def direct_connect(self) -> None:
        text, ok = QInputDialog.getText(self, "Connect to IP", "Address (ip or ip:port):")
        if not ok or not text.strip():
            return
        host, _, port = text.strip().partition(":")
        password, ok = QInputDialog.getText(self, "Password", "Password (leave empty if none):", QLineEdit.Password)
        if ok:
            self.join_requested.emit(host, int(port) if port.isdigit() else 7777, password)
