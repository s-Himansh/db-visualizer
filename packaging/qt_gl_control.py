"""A CONTROL for the hardware-drawing check: a plain Qt program, not Cairn, asks the X server for an OpenGL window and context the way
Cairn's web view does. It asks twice: for ordinary desktop OpenGL, and for OpenGL ES 2.0, which is what Chromium (so QtWebEngine) uses on
Linux and what the app's failure message ("QSurfaceFormat(version 2.0 ...") is actually asking for. If both fail here, the desktop (a virtual X
server) cannot give Qt any GLX; if only ES fails, the virtual X server offers desktop OpenGL but no OpenGL ES, which would stop every Qt
WebEngine program on it, whatever its libraries; if both work while Cairn fails, the difference is in the Cairn bundle.

    python3 packaging/qt_gl_control.py        exit 0 = both worked"""
import sys

from PySide6.QtGui import QGuiApplication, QOpenGLContext, QSurfaceFormat, QWindow

app = QGuiApplication(sys.argv)
print('platform:', app.platformName(), flush=True)


def attempt(label, renderable_type, version):
    fmt = QSurfaceFormat()
    fmt.setRenderableType(renderable_type)
    fmt.setVersion(*version)
    window = QWindow()
    window.setSurfaceType(QWindow.SurfaceType.OpenGLSurface)
    window.setFormat(fmt)
    window.create()
    context = QOpenGLContext()
    context.setFormat(window.requestedFormat())
    created = context.create()
    current = bool(created and context.makeCurrent(window))
    print(f'{label}: context created={created}, made current on a window={current}', flush=True)
    return current


desktop = attempt('desktop OpenGL', QSurfaceFormat.RenderableType.OpenGL, (2, 1))
es2 = attempt('OpenGL ES 2.0  ', QSurfaceFormat.RenderableType.OpenGLES, (2, 0))
sys.exit(0 if desktop and es2 else 1)
