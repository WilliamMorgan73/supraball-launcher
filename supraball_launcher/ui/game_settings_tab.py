"""The game's own settings: display, frame rate, graphics and mouse."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import gamesettings
from .widgets import spin_box

RESOLUTIONS = [(1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1080), (2560, 1440),
               (3440, 1440), (3840, 2160)]
DETAIL = [("Low", 0), ("Medium", 1), ("High", 2)]
ANISOTROPY = [("Off", 1), ("2x", 2), ("4x", 4), ("8x", 8), ("16x", 16)]
MSAA = [("Off", 1), ("2x", 2), ("4x", 4), ("8x", 8)]
EFFECTS = [
    ("DynamicShadows", "Dynamic shadows"),
    ("MotionBlur", "Motion blur"),
    ("DepthOfField", "Depth of field"),
    ("AmbientOcclusion", "Ambient occlusion"),
    ("Bloom", "Bloom"),
    ("bAllowLightShafts", "Light shafts"),
    ("LensFlares", "Lens flares"),
]


def _combo(items: list[tuple[str, object]]) -> QComboBox:
    c = QComboBox()
    for label, value in items:
        c.addItem(label, value)
    return c


def _select(combo: QComboBox, value) -> None:
    idx = combo.findData(value)
    if idx < 0:  # a value set elsewhere, e.g. a custom resolution: keep it selectable
        label = f"{value[0]} × {value[1]}" if isinstance(value, tuple) else str(value)
        combo.addItem(label, value)
        idx = combo.count() - 1
    combo.setCurrentIndex(idx)


def _form(title: str) -> tuple[QGroupBox, QFormLayout]:
    box = QGroupBox(title)
    f = QFormLayout(box)
    f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    f.setHorizontalSpacing(16)
    return box, f


class GameSettingsTab(QWidget):
    def __init__(self, get_paths, parent=None):
        super().__init__(parent)
        self.get_paths = get_paths  # callable -> GamePaths (raises PathError)
        self._loaded: dict = {}

        self.resolution = _combo([(f"{w} × {h}", (w, h)) for w, h in RESOLUTIONS])
        self.fullscreen = _combo([("Windowed", False), ("Fullscreen", True)])
        self.vsync = QCheckBox("VSync")
        self.screen_pct = spin_box(25, 200, suffix=" %")
        self.screen_pct.setToolTip("Render at this percentage of the window size, then scale")
        self.fps_cap = spin_box(0, 360, "Unlimited", " FPS")
        self.detail = _combo(DETAIL)
        self.anisotropy = _combo(ANISOTROPY)
        self.msaa = _combo(MSAA)
        self.effects = {key: QCheckBox(label) for key, label in EFFECTS}
        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.lineEdit().setTextMargins(6, 0, 0, 0)
        self.sensitivity.setRange(0.5, 100.0)
        self.sensitivity.setDecimals(1)
        self.sensitivity.setSingleStep(0.5)
        self.smoothing = QCheckBox("Mouse smoothing")
        self.invert = QCheckBox("Invert mouse")

        display, f = _form("Display")
        f.addRow("Resolution", self.resolution)
        f.addRow("Window", self.fullscreen)
        f.addRow("Render scale", self.screen_pct)
        f.addRow("", self.vsync)
        frame, f = _form("Frame rate")
        f.addRow("FPS cap", self.fps_cap)
        graphics, f = _form("Graphics")
        f.addRow("Detail", self.detail)
        f.addRow("Texture filtering", self.anisotropy)
        f.addRow("Anti-aliasing", self.msaa)
        for box in self.effects.values():
            f.addRow("", box)
        mouse, f = _form("Mouse")
        f.addRow("Sensitivity", self.sensitivity)
        f.addRow("", self.smoothing)
        f.addRow("", self.invert)

        left = QVBoxLayout()
        left.addWidget(display)
        left.addWidget(frame)
        left.addWidget(mouse)
        left.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(graphics)
        right.addStretch(1)
        columns = QHBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        form_widget = QWidget()
        form_widget.setLayout(columns)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.save_btn = QPushButton("Save", objectName="primary")
        self.save_btn.clicked.connect(self.save)
        revert = QPushButton("Revert")
        revert.setToolTip("Discard unsaved changes and show what's in the game's files")
        revert.clicked.connect(self.reload)
        open_dir = QPushButton("Open config folder")
        open_dir.clicked.connect(self._open_folder)
        self.status = QLabel("Changes apply the next time you start the game.", objectName="hint")
        self.status.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_btn)
        buttons.addWidget(revert)
        buttons.addWidget(open_dir)
        buttons.addWidget(self.status, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)
        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.values() == self._loaded:  # pick up changes made in game, unless there are unsaved edits
            self.reload()

    def values(self) -> dict:
        if not self._loaded:
            return {}
        w, h = self.resolution.currentData()
        fps = self.fps_cap.value()
        v = {
            "ResX": w, "ResY": h,
            "Fullscreen": self.fullscreen.currentData(),
            "UseVsync": self.vsync.isChecked(),
            "ScreenPercentage": float(self.screen_pct.value()),
            "bSmoothFrameRate": fps > 0,
            # The cap only applies while smoothing is on; keep the old number when switching it off.
            "MaxSmoothedFrameRate": fps or self._loaded["MaxSmoothedFrameRate"],
            "DetailMode": self.detail.currentData(),
            "MaxAnisotropy": self.anisotropy.currentData(),
            "MaxMultiSamples": self.msaa.currentData(),
            "MouseSensitivity": round(self.sensitivity.value(), 1),
            "bEnableMouseSmoothing": self.smoothing.isChecked(),
            "bInvertMouse": self.invert.isChecked(),
        }
        v.update({key: box.isChecked() for key, box in self.effects.items()})
        if round(self._loaded["MouseSensitivity"], 1) == v["MouseSensitivity"]:
            v["MouseSensitivity"] = self._loaded["MouseSensitivity"]  # don't rewrite 14.25 as 14.3
        return v

    def reload(self) -> None:
        try:
            paths = self.get_paths()
        except Exception as e:
            self.setEnabled(False)
            self.status.setText(str(e))
            return
        self.setEnabled(True)
        v = gamesettings.load(paths)
        _select(self.resolution, (v["ResX"], v["ResY"]))
        _select(self.fullscreen, v["Fullscreen"])
        self.vsync.setChecked(v["UseVsync"])
        self.screen_pct.setValue(round(v["ScreenPercentage"]))
        self.fps_cap.setValue(v["MaxSmoothedFrameRate"] if v["bSmoothFrameRate"] else 0)
        _select(self.detail, v["DetailMode"])
        _select(self.anisotropy, v["MaxAnisotropy"])
        _select(self.msaa, v["MaxMultiSamples"])
        for key, box in self.effects.items():
            box.setChecked(v[key])
        self.sensitivity.setValue(v["MouseSensitivity"])
        self.smoothing.setChecked(v["bEnableMouseSmoothing"])
        self.invert.setChecked(v["bInvertMouse"])
        self._loaded = v
        self._loaded = self.values()  # normalised the same way the form reads it back

    def save(self) -> None:
        if gamesettings.game_running():
            QMessageBox.information(self, "Game is running",
                                    "Close Supraball first. The game saves its own settings when it quits "
                                    "and would overwrite these changes.")
            return
        try:
            written = gamesettings.save(self.get_paths(), self.values())
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save settings", str(e))
            return
        self._loaded = self.values()
        self.status.setText("Saved. Changes apply the next time you start the game."
                            if written else "Nothing to save.")

    def _open_folder(self) -> None:
        try:
            folder = self.get_paths().game_dir / "UDKGame/Config"
        except Exception:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
