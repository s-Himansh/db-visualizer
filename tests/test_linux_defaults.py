"""The environment the packaged Linux app starts its web view with: software drawing and no Chromium sandbox by default (found by trial:
every way of starting without OpenGL worked and the plain one aborted with 'Could not initialize GLX' where there was no GLX),
the user's own settings are never overridden, and DBV_GPU=1 brings hardware drawing back."""
import db


def test_the_defaults_draw_in_software_and_skip_the_sandbox():
    env = {}
    db.linux_web_view_defaults(env)
    assert env['QTWEBENGINE_CHROMIUM_FLAGS'] == '--no-sandbox --disable-gpu'
    assert env['QT_QUICK_BACKEND'] == 'software' and env['QT_XCB_GL_INTEGRATION'] == 'none'


def test_what_the_user_set_is_never_overridden():
    env = {'QTWEBENGINE_CHROMIUM_FLAGS': '--my-flag', 'QT_QUICK_BACKEND': 'rhi', 'QT_XCB_GL_INTEGRATION': 'xcb_glx'}
    db.linux_web_view_defaults(env)
    assert env == {'QTWEBENGINE_CHROMIUM_FLAGS': '--my-flag', 'QT_QUICK_BACKEND': 'rhi', 'QT_XCB_GL_INTEGRATION': 'xcb_glx'}


def test_dbv_gpu_brings_hardware_drawing_back_but_keeps_the_sandbox_off():
    env = {'DBV_GPU': '1'}
    db.linux_web_view_defaults(env)
    assert env['QTWEBENGINE_CHROMIUM_FLAGS'] == '--no-sandbox'
    assert 'QT_QUICK_BACKEND' not in env and 'QT_XCB_GL_INTEGRATION' not in env
