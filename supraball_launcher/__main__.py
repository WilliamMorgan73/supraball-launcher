import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from supraball_launcher.ui import theme
from supraball_launcher.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Supraball Launcher")
    theme.load_fonts()
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(theme.app_icon())
    window = MainWindow()
    window.show()

    # Ctrl+C in the terminal: close cleanly (stopping any hosted server) instead of
    # raising KeyboardInterrupt inside whatever Qt callback happens to be running.
    signal.signal(signal.SIGINT, lambda *_: window.quit_from_signal())
    # Python only runs signal handlers between bytecodes, so wake the interpreter regularly.
    wake = QTimer(interval=250)
    wake.timeout.connect(lambda: None)
    wake.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
