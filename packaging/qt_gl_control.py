"""A CONTROL for the hardware-drawing check: a plain Qt program, not Cairn, asks the X server for an OpenGL window and context the way
Cairn's web view does. If it fails here too, the desktop (a virtual X server) cannot give Qt any GLX, and a Cairn failure says nothing
about the app. If it works while Cairn fails, the difference is in the Cairn bundle. Needs PySide6 (the same minor version as the bundle).

    python3 packaging/qt_gl_control.py        exit 0 = OpenGL worked, 1 = it did not"""
import sys

from PySide6.QtGui import QGuiApplication, QOpenGLContext, QSurfaceFormat, QWindow

app = QGuiApplication(sys.argv)
print('platform:', app.platformName(), flush=True)
window = QWindow()
window.setSurfaceType(QWindow.SurfaceType.OpenGLSurface)
window.setFormat(QSurfaceFormat.defaultFormat())
window.create()
context = QOpenGLContext()
context.setFormat(window.requestedFormat())
created = context.create()
print('context created:', created, flush=True)
current = created and context.makeCurrent(window)
print('made current on a window:', bool(current), flush=True)
if current:
    f = context.functions()
    print('GL renderer:', f.glGetString(0x1F01), '| version:', f.glGetString(0x1F02), flush=True)
sys.exit(0 if current else 1)
