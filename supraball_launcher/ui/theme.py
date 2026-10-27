"""Match-day theme: turf, chalk lines, red vs blue, and the yellow ball."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFontDatabase, QIcon, QPainter, QPainterPath, QPalette, QPixmap, QRadialGradient

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Sampled from the Supraball splash and icon.
RED = "#DF1E1E"
RED_DEEP = "#A81414"
BLUE = "#1D7EDD"
BLUE_DEEP = "#145DA6"
BALL = "#F5E400"
BALL_LIGHT = "#FFF25A"
BALL_SHADE = "#D6D600"
INK = "#10151F"  # logo outline; text on yellow
TURF = "#14482F"
TURF_STRIPE = "#185436"
TURF_DEEP = "#0C3020"
TURF_DEEPER = "#08241A"
LINE = "#2E6A4C"  # quiet chalk line
CHALK = "#F2F7F3"
CHALK_DIM = "#A9C4B3"
MUTED = "#6F927F"

DISPLAY = "Lilita One"
BODY = "Nunito"


def load_fonts() -> None:
    for f in (ASSETS / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))


def ping_color(ms: int | None) -> QColor:
    if ms is None:
        return QColor(MUTED)
    if ms < 80:
        return QColor(CHALK)
    if ms < 180:
        return QColor(BALL)
    return QColor("#FF6B6B")  # lighter than RED so it stays readable on turf


def palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.Window: TURF, QPalette.WindowText: CHALK, QPalette.Base: TURF_DEEP,
        QPalette.AlternateBase: "#0F3825", QPalette.Text: CHALK, QPalette.Button: TURF_DEEP,
        QPalette.ButtonText: CHALK, QPalette.Highlight: BALL, QPalette.HighlightedText: INK,
        QPalette.ToolTipBase: CHALK, QPalette.ToolTipText: INK, QPalette.PlaceholderText: MUTED,
        QPalette.Link: BLUE, QPalette.BrightText: CHALK,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(MUTED))
    return p


def stylesheet() -> str:
    icons = (ASSETS / "icons").as_posix()
    mono = QFontDatabase.systemFont(QFontDatabase.FixedFont).family()
    return f"""
QWidget {{ font-family: "{BODY}"; font-size: 13px; color: {CHALK}; }}
QMainWindow, QDialog, QMessageBox {{ background: {TURF}; }}
QToolTip {{ background: {CHALK}; color: {INK}; border: none; padding: 5px 8px; }}

QStatusBar {{ background: {TURF_DEEPER}; color: {CHALK_DIM}; }}
QStatusBar QLabel {{ color: {CHALK_DIM}; }}

QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ background: transparent; }}
QTabWidget::tab-bar {{ left: 16px; }}
QTabBar::tab {{
    font-family: "{DISPLAY}"; font-size: 16px; color: {CHALK_DIM};
    background: transparent; border: 2px solid {LINE};
    border-radius: 14px;  /* Qt drops the rounding entirely if this exceeds half the tab height */
    padding: 5px 20px; margin: 12px 8px 8px 0;
}}
QTabBar::tab:hover:!selected {{ color: {CHALK}; border-color: {CHALK_DIM}; }}
QTabBar::tab:selected {{ background: {CHALK}; color: {TURF_DEEP}; border-color: {CHALK}; }}
QTabBar::tab:focus {{ border-color: {BLUE}; }}

QPushButton {{
    background: {TURF_DEEP}; color: {CHALK}; font-weight: 700;
    border: 2px solid {LINE}; border-radius: 14px; padding: 6px 16px; min-height: 18px;
}}
QPushButton:hover {{ border-color: {CHALK_DIM}; }}
QPushButton:pressed {{ background: {TURF_DEEPER}; }}
QPushButton:focus {{ border-color: {BLUE}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: #23523A; background: transparent; }}
QPushButton#primary {{
    font-family: "{DISPLAY}"; font-size: 16px; font-weight: 400;
    background: {BALL}; color: {INK}; border: 2px solid {BALL_SHADE}; padding: 5px 24px;
}}
QPushButton#primary:hover {{ background: {BALL_LIGHT}; }}
QPushButton#primary:pressed {{ background: {BALL_SHADE}; }}
QPushButton#primary:focus {{ border-color: {INK}; }}
QPushButton#primary:disabled {{ background: #3C5E2E; color: #7E9A6E; border-color: #3C5E2E; }}
QPushButton#danger {{ background: {RED}; color: white; border-color: {RED_DEEP}; }}
QPushButton#danger:hover {{ background: #EE3434; }}
QPushButton#danger:disabled {{ color: {MUTED}; border-color: #23523A; background: transparent; }}
QPushButton#onTeam {{ background: transparent; color: white; border: 2px solid rgba(255,255,255,0.7); }}
QPushButton#onTeam:hover {{ background: rgba(255,255,255,0.15); border-color: white; }}

QLineEdit, QSpinBox, QComboBox {{
    background: {TURF_DEEP}; color: {CHALK}; border: 2px solid {LINE}; border-radius: 8px;
    padding: 4px 8px; min-height: 18px;
    selection-background-color: {BALL}; selection-color: {INK};
}}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {CHALK_DIM}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {BLUE}; }}
QLineEdit:disabled, QSpinBox:disabled {{ color: {MUTED}; border-color: #23523A; }}
QLineEdit[readOnly="true"] {{ background: {TURF_DEEPER}; color: {CHALK_DIM}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({icons}/chevron-down.svg); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {TURF_DEEP}; border: 2px solid {LINE}; outline: 0; padding: 4px;
    selection-background-color: {BALL}; selection-color: {INK};
}}
QSpinBox QLineEdit {{ border: none; background: transparent; padding: 0; min-height: 0; }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; width: 20px; background: transparent; }}
QSpinBox::up-arrow {{ image: url({icons}/chevron-up.svg); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({icons}/chevron-down.svg); width: 10px; height: 10px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 2px solid {CHALK_DIM}; border-radius: 9px; background: {TURF_DEEP};
}}
QCheckBox::indicator:hover {{ border-color: {CHALK}; }}
QCheckBox::indicator:checked {{ background: {BALL}; border-color: {BALL}; image: url({icons}/check.svg); }}
QCheckBox:focus {{ color: white; }}
QCheckBox::indicator:focus {{ border-color: {BLUE}; }}

QTableView {{
    background: rgba(8, 36, 26, 0.93); alternate-background-color: rgba(16, 58, 39, 0.93);
    border: 2px solid {LINE}; border-radius: 10px; gridline-color: transparent;
    selection-background-color: {BALL}; selection-color: {INK}; outline: 0;
}}
QTableView:focus {{ border-color: {BLUE}; }}
QTableView::item {{ padding: 0 8px; border: none; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent; color: {CHALK_DIM}; font-weight: 800;
    border: none; border-bottom: 2px solid {CHALK}; padding: 8px;
}}
QHeaderView::down-arrow {{ image: url({icons}/chevron-down.svg); width: 10px; height: 10px; }}
QHeaderView::up-arrow {{ image: url({icons}/chevron-up.svg); width: 10px; height: 10px; }}
QLabel#emptyState {{ color: {CHALK_DIM}; font-size: 15px; background: transparent; }}

QGroupBox {{
    font-family: "{DISPLAY}"; font-size: 16px; color: {CHALK};
    border: 2px solid {LINE}; border-radius: 12px; margin-top: 16px; padding: 14px 10px 8px 10px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; }}
QLabel#heading {{ font-family: "{DISPLAY}"; font-size: 16px; color: {CHALK}; }}
QLabel#hint {{ color: {CHALK_DIM}; }}
QLabel#statePill {{
    border: 2px solid {LINE}; border-radius: 12px; padding: 3px 12px; color: {CHALK_DIM}; font-weight: 700;
}}
QLabel#statePill[live="true"] {{ background: {BALL}; border-color: {BALL}; color: {INK}; }}
QLabel#banner {{ border: 2px solid {LINE}; border-radius: 10px; padding: 8px 12px; color: {CHALK}; }}
QLabel#banner[level="ok"] {{ border-color: {BALL}; }}
QLabel#banner[level="warn"] {{ border-color: {RED}; background: {TURF_DEEPER}; }}

QToolButton#itemCard {{
    background: {TURF_DEEP}; color: {CHALK}; border: 2px solid {LINE}; border-radius: 14px;
    padding: 8px 6px 6px 6px; font-weight: 700;
}}
QToolButton#itemCard:hover {{ border-color: {CHALK_DIM}; }}
QToolButton#itemCard:focus {{ border-color: {BLUE}; }}
QToolButton#itemCard[equipped="true"] {{ background: {BALL}; color: {INK}; border-color: {BALL_SHADE}; }}
QToolButton#itemCard:disabled {{ color: {MUTED}; }}
QToolButton#itemCard[equipped="true"]:disabled {{ color: {INK}; }}
QToolButton#itemCard[owned="false"] {{ background: transparent; color: {CHALK_DIM}; border: 2px dashed {LINE}; }}
QToolButton#itemCard[owned="false"]:hover {{ border-color: {CHALK_DIM}; color: {CHALK}; }}
QLabel#preview {{ background: {TURF_DEEP}; border: 2px solid {CHALK}; border-radius: 14px; color: {CHALK_DIM}; }}

QPlainTextEdit#log, QLineEdit#command {{ font-family: "{mono}"; font-size: 12px; }}
QPlainTextEdit#log {{
    background: {TURF_DEEPER}; color: {CHALK_DIM}; border: 2px solid {LINE}; border-radius: 10px; padding: 6px;
    selection-background-color: {BALL}; selection-color: {INK};
}}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QSplitter::handle {{ background: transparent; width: 10px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {LINE}; border-radius: 3px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {CHALK_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def paint_ball(p: QPainter, rect: QRectF) -> None:
    """The Supraball ball: flat yellow, a shaded crescent lower right, a white glint upper left."""
    d = rect.width()
    circle = QPainterPath()
    circle.addEllipse(rect)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setClipPath(circle)
    p.fillPath(circle, QColor(BALL_SHADE))
    lit = QRectF(rect.x() - d * 0.07, rect.y() - d * 0.07, d * 0.98, d * 0.98)
    grad = QRadialGradient(lit.center() - QPointF(d * 0.15, d * 0.15), d * 0.7)
    grad.setColorAt(0, QColor(BALL_LIGHT))
    grad.setColorAt(0.55, QColor(BALL))
    p.setBrush(QBrush(grad))
    p.drawEllipse(lit)
    p.setBrush(QColor(255, 255, 255, 235))
    p.translate(rect.x() + d * 0.32, rect.y() + d * 0.24)
    p.rotate(-30)
    p.drawEllipse(QRectF(-d * 0.12, -d * 0.075, d * 0.24, d * 0.15))
    p.restore()


def ball_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint_ball(p, QRectF(1, 1, size - 2, size - 2))
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        icon.addPixmap(ball_pixmap(size))
    return icon
