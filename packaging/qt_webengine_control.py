"""The decisive CONTROL for the hardware-drawing check: a plain Qt WebEngine program, with no Cairn and no PyInstaller, from the same pip packages
as the bundle, shows a page. Run it with the settings under test (for example QTWEBENGINE_CHROMIUM_FLAGS and DBV-style GL settings in the
environment). If it fails on a desktop where Cairn fails, the failure is Qt WebEngine on that desktop, not Cairn's packaging.

    python3 packaging/qt_webengine_control.py        exit 0 = the page loaded, 1 = it did not"""
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
view = QWebEngineView()
view.resize(500, 300)
loaded = []


def finished(ok):
    loaded.append(ok)
    print('loadFinished:', ok, flush=True)
    QTimer.singleShot(300, app.quit)


view.loadFinished.connect(finished)
view.setHtml('<h1 style="font-family:sans-serif">Qt WebEngine control</h1>')
view.show()
QTimer.singleShot(25000, lambda: (print('timeout: the page never loaded', flush=True), app.quit()))
app.exec()
sys.exit(0 if loaded and loaded[0] else 1)
