"""Custom-painted pieces of the match-day theme."""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QPushButton, QSpinBox, QStyle, QStyledItemDelegate, QWidget

from . import theme


def spin_box(lo: int, hi: int, special: str | None = None, suffix: str = "") -> QSpinBox:
    s = QSpinBox()
    s.lineEdit().setTextMargins(6, 0, 0, 0)  # QSS padding doesn't reach the spin box's inner editor
    s.setRange(lo, hi)
    if special:
        s.setSpecialValueText(special)  # shown at the minimum value
    if suffix:
        s.setSuffix(suffix)
    return s


class Scoreboard(QWidget):
    """Red wing vs blue wing with the ball on the halfway line, like the Supraball logo.

    The red side counts servers, the blue side counts players.
    """

    HEIGHT = 104
    BALL = 80

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.servers = 0
        self.players = 0
        self._shown = [0.0, 0.0]
        self._anim = QVariantAnimation(self, duration=700, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._from = (0, 0)
        self._bounce_t = 0.0
        self._bounce = QTimer(self, interval=16, timeout=self._tick)

        self.settings_btn = QPushButton("Settings", self, objectName="onTeam")
        self.play_btn = QPushButton("Play", self, objectName="primary")
        self.play_btn.setToolTip("Start Supraball")

    # --- state ----------------------------------------------------------
    def set_counts(self, servers: int, players: int) -> None:
        self._from = tuple(self._shown)
        self.servers, self.players = servers, players
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_anim(self, t: float) -> None:
        self._shown = [self._from[0] + (self.servers - self._from[0]) * t,
                       self._from[1] + (self.players - self._from[1]) * t]
        self.update()

    def set_busy(self, busy: bool) -> None:
        if busy:
            self._bounce.start()
        else:
            self._bounce.stop()
            self._bounce_t = 0.0
            self.update()

    def _tick(self) -> None:
        self._bounce_t += 0.016
        self.update()

    # --- layout & painting ---------------------------------------------
    def resizeEvent(self, event) -> None:
        h = self.height()
        self.settings_btn.adjustSize()
        self.settings_btn.move(16, (h - self.settings_btn.height()) // 2)
        self.play_btn.adjustSize()
        self.play_btn.resize(max(self.play_btn.width(), 104), self.play_btn.height() + 6)
        self.play_btn.move(self.width() - self.play_btn.width() - 18, (h - self.play_btn.height()) // 2)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx = w / 2
        gap_top, gap_bottom = 96, 70  # half-widths of the white wedge between the wings

        p.fillRect(self.rect(), QColor(theme.CHALK))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.RED))
        p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(cx - gap_top, 0), QPointF(cx - gap_bottom, h), QPointF(0, h)]))
        p.setBrush(QColor(theme.BLUE))
        p.drawPolygon(QPolygonF([QPointF(cx + gap_top, 0), QPointF(w, 0), QPointF(w, h), QPointF(cx + gap_bottom, h)]))
        # A darker band along the bottom edge reads as the board's frame.
        p.fillRect(QRectF(0, h - 4, w, 4), QColor(theme.INK))

        # Ball on the halfway line; it hops while the server list is loading.
        hop = abs(math.sin(self._bounce_t * 7)) * 12 if self._bounce.isActive() else 0
        ring = self.BALL + 10
        p.setBrush(QColor(theme.CHALK))
        lift = 12  # the ball sits high so it shows above the wordmark, like the logo
        p.drawEllipse(QRectF(cx - ring / 2, (h - ring) / 2 - lift - hop, ring, ring))
        theme.paint_ball(p, QRectF(cx - self.BALL / 2, (h - self.BALL) / 2 - lift - hop, self.BALL, self.BALL))

        self._draw_wordmark(p, cx, h)

        # Counts: red side right-aligned towards the middle, blue side left-aligned from it.
        left_edge = self.settings_btn.geometry().right() + 24
        right_edge = self.play_btn.geometry().left() - 24
        self._draw_count(p, round(self._shown[0]), "server" if self.servers == 1 else "servers",
                         QRectF(left_edge, 0, cx - gap_top - 24 - left_edge, h), Qt.AlignRight)
        self._draw_count(p, round(self._shown[1]), "player" if self.players == 1 else "players",
                         QRectF(cx + gap_top + 24, 0, right_edge - cx - gap_top - 24, h), Qt.AlignLeft)
        p.end()

    def _draw_wordmark(self, p: QPainter, cx: float, h: float) -> None:
        font = QFont(theme.DISPLAY)
        font.setPixelSize(38)
        path = QPainterPath()
        path.addText(0, 0, font, "Supraball")
        r = path.boundingRect()
        path.translate(cx - r.width() / 2 - r.x(), h / 2 + 24)
        p.save()
        p.translate(0, 3)  # hard drop shadow
        p.fillPath(path, QColor(0, 0, 0, 90))
        p.restore()
        p.strokePath(path, QPen(QColor(theme.INK), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.fillPath(path, QColor("white"))

    def _draw_count(self, p: QPainter, value: int, label: str, area: QRectF, align) -> None:
        if area.width() < 60:
            return
        num_font = QFont(theme.DISPLAY)
        num_font.setPixelSize(40)
        label_font = QFont(theme.DISPLAY)
        label_font.setPixelSize(20)
        num = str(value)
        p.setFont(num_font)
        num_w = p.fontMetrics().horizontalAdvance(num)
        p.setFont(label_font)
        label_w = p.fontMetrics().horizontalAdvance(label)
        gap = 8
        total = num_w + gap + label_w
        x = area.right() - total if align == Qt.AlignRight else area.left()
        baseline = area.center().y() + 14
        p.setPen(QColor("white"))
        p.setFont(num_font)
        p.drawText(QPointF(x, baseline), num)
        p.setPen(QColor(255, 255, 255, 215))
        p.setFont(label_font)
        p.drawText(QPointF(x + num_w + gap, baseline), label)


class PitchBackground(QWidget):
    """Freshly mown turf: alternating horizontal stripes."""

    STRIPE = 56

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.TURF))
        stripe = QColor(theme.TURF_STRIPE)
        for i, y in enumerate(range(0, self.height(), self.STRIPE)):
            if i % 2:
                p.fillRect(0, y, self.width(), self.STRIPE, stripe)
        p.end()


class PlayersDelegate(QStyledItemDelegate):
    """Players as pips: filled for each player, hollow for each open slot, then 'n/max'."""

    PIP = 9
    PIP_GAP = 4
    MAX_PIPS = 12

    def __init__(self, entry_role: int, parent=None):
        super().__init__(parent)
        self.entry_role = entry_role

    def paint(self, painter: QPainter, option, index) -> None:
        self.initStyleOption(option, index)
        option.text = ""
        style = option.widget.style() if option.widget else None
        if style:
            style.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        s = index.siblingAtColumn(0).data(self.entry_role)
        if s is None:
            return
        selected = bool(option.state & QStyle.State_Selected)
        fill = QColor(theme.INK if selected else theme.BALL)
        hollow = QColor(theme.INK if selected else theme.CHALK_DIM)
        text_color = QColor(theme.INK if selected else theme.CHALK)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        x = r.left() + 10
        cy = r.center().y() + 0.5
        if 0 < s.max_players <= self.MAX_PIPS:
            for i in range(s.max_players):
                pip = QRectF(x, cy - self.PIP / 2, self.PIP, self.PIP)
                if i < s.players:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(fill)
                    painter.drawEllipse(pip)
                else:
                    painter.setPen(QPen(hollow, 1.5))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(pip.adjusted(0.75, 0.75, -0.75, -0.75))
                x += self.PIP + self.PIP_GAP
            x += 4
        text = f"{s.players}/{s.max_players}" + (f" +{s.spectators}" if s.spectators else "")
        painter.setPen(text_color)
        painter.setFont(option.font)
        painter.drawText(QRectF(x, r.top(), r.right() - x, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        s = index.siblingAtColumn(0).data(self.entry_role)
        if s is not None and 0 < s.max_players <= self.MAX_PIPS:
            size.setWidth(20 + s.max_players * (self.PIP + self.PIP_GAP) + 50)
        return size
