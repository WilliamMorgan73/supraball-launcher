"""Costume: see your player and change what they wear, using your Steam Inventory items."""

from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)

from .. import lobby, steamhelper
from ..paths import PathError
from .costume_art import CostumeArt, ensure_art

SLOTS = [("skin", "Skins"), ("hat", "Hats"), ("gun", "Guns")]
SLOT_NAMES = {"skin": "Skin", "hat": "Hat", "gun": "Gun"}
KEEPALIVE_MS = 10_000  # the official launcher pings every 10 s
PREVIEW_MAX_HEIGHT = 350
PREVIEW_MIN_HEIGHT = 180


class FlowLayout(QLayout):
    """Lays children out left to right, wrapping onto new rows."""

    def __init__(self, parent=None, spacing: int = 10):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect: QRect, apply: bool) -> int:
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self._items:
            if item.isEmpty():  # hidden widget, e.g. filtered out by search
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and row_height:
                x, y, row_height = rect.x(), y + row_height + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y()


class CostumeWorker(QObject):
    """Owns the Steam session and lobby connection on a background thread."""

    loaded = Signal(object, list, object)  # SteamSession, equipped definitions, art dir (Path | None)
    equipped_changed = Signal(list)
    failed = Signal(str)
    busy = Signal(bool)

    def __init__(self, get_paths, master_host: str):
        super().__init__()
        self.get_paths = get_paths
        self.master_host = master_host
        self.session: steamhelper.SteamSession | None = None
        self.client: lobby.LobbyClient | None = None
        self.jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def load(self) -> None:
        self.jobs.put(("load",))

    def equip(self, definition: int, on: bool) -> None:
        self.jobs.put(("equip", definition, on))

    def keepalive(self) -> None:
        if self.client and self.jobs.empty():
            self.jobs.put(("ping",))

    def stop(self) -> None:
        self.jobs.put(("stop",))

    def _connect(self, fresh_session: bool) -> None:
        if self.client:
            self.client.close()
            self.client = None
        if fresh_session or self.session is None:
            self.session = steamhelper.fetch(self.get_paths())
        client = lobby.LobbyClient(self.master_host)
        client.connect(self.session)
        self.client = client

    def _with_connection(self, action):
        """Run action(client); on a dropped connection reconnect once, getting a new ticket if needed."""
        if self.client is None:
            self._connect(fresh_session=False)
        try:
            return action(self.client)
        except (lobby.LobbyError, OSError):
            try:
                self._connect(fresh_session=False)
            except lobby.LobbyError:
                self._connect(fresh_session=True)  # ticket expired
            return action(self.client)

    def _run(self) -> None:
        while True:
            job = self.jobs.get()
            if job[0] == "stop":
                if self.client:
                    self.client.close()
                return
            if job[0] == "ping":
                try:
                    self.client.ping()
                except (lobby.LobbyError, OSError, AttributeError):
                    self.client = None  # reconnect on the next real action
                continue
            self.busy.emit(True)
            try:
                if job[0] == "load":
                    self._connect(fresh_session=True)
                    equipped = self.client.equipped()
                    self.loaded.emit(self.session, equipped, ensure_art(self.get_paths()))
                elif job[0] == "equip":
                    _, definition, on = job
                    equipped = self._with_connection(lambda c: (c.set_equipped(definition, on), c.equipped())[1])
                    self.equipped_changed.emit(equipped)
            except (steamhelper.SteamError, lobby.LobbyError, PathError, OSError) as e:
                self.failed.emit(str(e))
            finally:
                self.busy.emit(False)


class ItemCard(QToolButton):
    def __init__(self, item: steamhelper.Item, icon, parent=None):
        super().__init__(parent, objectName="itemCard")
        self.item = item
        self.setText(item.name)
        if icon is not None:
            self.setIcon(QIcon(icon))
            self.setIconSize(QSize(56, 96) if item.slot == "skin" else QSize(80, 80))
            self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            self.setFixedSize(132, 140)
        else:
            self.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self.setFixedSize(132, 56)
        self.setCursor(Qt.PointingHandCursor)
        self.set_equipped(False)

    def set_equipped(self, on: bool) -> None:
        self.setProperty("equipped", on)
        self.setProperty("owned", self.item.owned)
        if not self.item.owned:
            self.setToolTip(f"You don't own {self.item.name}. Click to find it on the Steam Market."
                            if self.item.marketable else f"You don't own {self.item.name}. It comes from drops or chests.")
            self.setCursor(Qt.PointingHandCursor if self.item.marketable else Qt.ArrowCursor)
        elif on:
            self.setToolTip(f"You're wearing {self.item.name}. Click to take it off.")
        else:
            self.setToolTip(f"Click to wear {self.item.name}.")
        self.style().unpolish(self)
        self.style().polish(self)


class CostumeTab(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, settings, get_paths, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.worker = CostumeWorker(get_paths, settings.master_host)
        self.worker.loaded.connect(self._on_loaded)
        self.worker.equipped_changed.connect(self._show_equipped)
        self.worker.failed.connect(self._on_failed)
        self.worker.busy.connect(self._on_busy)
        self.started = False
        self.art = CostumeArt(None)
        self.items: dict[int, steamhelper.Item] = {}  # owned, wearable
        self.catalogue: list[steamhelper.Item] = []  # every wearable item in the game
        self.slot_sections: list[tuple[QLabel, QWidget, list[ItemCard]]] = []
        self.cards: dict[int, ItemCard] = {}
        self.equipped: list[int] = []
        self.trying_on: int | None = None

        self.status = QLabel("Your costume loads from Steam when you open this tab.", objectName="hint")
        self.status.setWordWrap(True)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.clicked.connect(self.reload)
        self.show_all = QCheckBox("Show all items")
        self.show_all.setToolTip("Preview every skin and hat in the game. You can only wear items you own.")
        self.show_all.setChecked(settings.costume_show_all)
        self.show_all.toggled.connect(self._on_show_all)
        self.search = QLineEdit(placeholderText="Search items…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(240)
        self.search.setVisible(settings.costume_show_all)
        self.search.textChanged.connect(self._apply_search)
        top = QHBoxLayout()
        top.addWidget(self.status, 1)
        top.addWidget(self.search)
        top.addWidget(self.show_all)
        top.addWidget(self.reload_btn)

        # Left: the player as they'll look, with what's in each slot underneath.
        self.preview = QLabel(alignment=Qt.AlignCenter, objectName="preview")
        self.preview_size = QSize(210, PREVIEW_MAX_HEIGHT)
        self.slot_labels = {slot: QLabel("Nothing") for slot, _ in SLOTS}
        slots_form = QFormLayout()
        slots_form.setHorizontalSpacing(12)
        for slot, label in self.slot_labels.items():
            label.setWordWrap(True)
            slots_form.addRow(QLabel(SLOT_NAMES[slot], objectName="hint"), label)
        left = QVBoxLayout()
        left.addWidget(self.preview)
        left.addSpacing(6)
        left.addLayout(slots_form)
        left.addStretch(1)

        self.sections = QWidget()
        self.sections_layout = QVBoxLayout(self.sections)
        self.sections_layout.setContentsMargins(0, 0, 8, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.sections)

        body = QHBoxLayout()
        body.setSpacing(18)
        body.addLayout(left)
        body.addWidget(scroll, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addSpacing(4)
        layout.addLayout(body, 1)

        self.keepalive = QTimer(self, interval=KEEPALIVE_MS, timeout=self.worker.keepalive)
        self._fit_preview()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_preview()

    def _fit_preview(self) -> None:
        """Size the player picture to the room left after the status line and the slot names."""
        height = max(PREVIEW_MIN_HEIGHT, min(PREVIEW_MAX_HEIGHT, self.height() - 160))
        self.preview_size = QSize(round(height * 280 / 467), height)
        self.preview.setFixedSize(self.preview_size.width() + 8, height + 8)
        self._render_preview()

    # --- loading ----------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.started:
            self.started = True
            self.reload()

    def reload(self) -> None:
        self.worker.master_host = self.settings.master_host
        self.status.setText("Signing in with Steam…")
        self.worker.load()

    def shutdown(self) -> None:
        self.keepalive.stop()
        self.worker.stop()

    def _on_busy(self, busy: bool) -> None:
        self.reload_btn.setEnabled(not busy)
        for card in self.cards.values():
            card.setEnabled(not busy)
        self.busy_changed.emit(busy)

    def _on_failed(self, message: str) -> None:
        self.status.setText(f"{message} Press Reload to try again.")

    def _on_loaded(self, session: steamhelper.SteamSession, equipped: list[int], art_dir) -> None:
        self.art = CostumeArt(art_dir)
        wearable = [i for i in session.items if i.slot]
        self.items = {i.definition: i for i in wearable}
        self.catalogue = session.catalogue
        self._build_sections()
        self._show_equipped(equipped)
        self.keepalive.start()
        count = len(wearable)
        self.status.setText(f"Signed in as {session.name}. Hover an item to try it on, click to wear it. "
                            f"You own {count} item{'s' if count != 1 else ''} you can wear.")

    def _on_show_all(self, on: bool) -> None:
        self.settings.costume_show_all = on
        self.settings.save()
        self.search.setVisible(on)
        if not on:
            self.search.clear()
        if self.items or self.catalogue:
            self._build_sections()
            self._show_equipped(self.equipped)

    def _shown_items(self) -> list[steamhelper.Item]:
        if not self.show_all.isChecked():
            return list(self.items.values())
        # Owned items first in each slot; unowned ones only when there's art to preview them with.
        shown = [i for i in self.catalogue if i.owned or self.art.has_art(i.slot, i.definition)]
        return sorted(shown, key=lambda i: (i.slot, not i.owned, i.name.lower()))

    def _build_sections(self) -> None:
        items = self._shown_items()
        self.slot_sections: list[tuple[QLabel, QWidget, list[ItemCard]]] = []
        while self.sections_layout.count():
            child = self.sections_layout.takeAt(0)
            if child.widget():
                child.widget().hide()  # deleteLater waits for the event loop; don't draw it meanwhile
                child.widget().deleteLater()
        self.cards.clear()
        for slot, title in SLOTS:
            slot_items = [i for i in items if i.slot == slot]
            if not slot_items:
                continue
            owned = sum(i.owned for i in slot_items)
            heading = QLabel(f"{title} ({owned} of {len(slot_items)})" if self.show_all.isChecked()
                             else f"{title} ({len(slot_items)})", objectName="heading")
            self.sections_layout.addWidget(heading)
            box = QWidget()
            flow = FlowLayout(box)
            slot_cards = []
            for item in slot_items:
                card = ItemCard(item, self.art.icon(slot, item.definition))
                slot_cards.append(card)
                card.clicked.connect(lambda _=False, d=item.definition: self._toggle(d))
                card.installEventFilter(self)
                flow.addWidget(card)
                self.cards[item.definition] = card
            self.slot_sections.append((heading, box, slot_cards))
            self.sections_layout.addWidget(box)
            self.sections_layout.addSpacing(10)
        if not items:
            empty = QLabel("You don't own any costume items yet. Items you get in Supraball show up here.",
                           objectName="emptyState")
            empty.setWordWrap(True)
            self.sections_layout.addWidget(empty)
        self.sections_layout.addStretch(1)
        self._apply_search()

    def _apply_search(self) -> None:
        query = self.search.text().strip().lower()
        for heading, box, cards in self.slot_sections:
            matches = 0
            for card in cards:
                card.setVisible(not query or query in card.item.name.lower())
                matches += card.isVisibleTo(box)
            heading.setVisible(matches > 0)
            box.setVisible(matches > 0)
            box.layout().invalidate()
    # --- trying on and equipping -------------------------------------------
    def eventFilter(self, obj, event) -> bool:
        if isinstance(obj, ItemCard) and obj.item.slot in ("skin", "hat"):
            if event.type() == QEvent.Enter:
                self.trying_on = obj.item.definition
                self._render_preview()
            elif event.type() == QEvent.Leave and self.trying_on == obj.item.definition:
                self.trying_on = None
                self._render_preview()
        return super().eventFilter(obj, event)

    def _worn(self, slot: str) -> int | None:
        if self.trying_on is not None and self.cards[self.trying_on].item.slot == slot:
            return self.trying_on
        return next((d for d in self.equipped if d in self.items and self.items[d].slot == slot), None)

    def _render_preview(self) -> None:
        if not self.art.available:
            self.preview.setText("Your player appears here\nonce your costume loads.")
            return
        pixmap = self.art.character(self._worn("skin"), self._worn("hat"))
        self.preview.setPixmap(pixmap.scaled(self.preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _toggle(self, definition: int) -> None:
        if definition not in self.items:  # not owned: never sent to the server
            item = self.cards[definition].item
            if item.marketable:
                QDesktopServices.openUrl(QUrl(steamhelper.market_url(item)))
            return
        item = self.items[definition]
        wearing = definition in self.equipped
        self.status.setText(f"Taking off {item.name}…" if wearing else f"Putting on {item.name}…")
        self.worker.equip(definition, not wearing)

    def _show_equipped(self, equipped: list[int]) -> None:
        self.equipped = list(equipped)
        for definition, card in self.cards.items():
            card.set_equipped(definition in self.equipped)
        for slot, label in self.slot_labels.items():
            current = next((self.items[d] for d in self.equipped if d in self.items and self.items[d].slot == slot), None)
            label.setText(current.name if current else "Nothing")
        self._render_preview()
        if self.items and self.status.text().endswith("…"):
            self.status.setText("Saved. You'll wear this the next time you join a game.")
