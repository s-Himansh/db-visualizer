# Layout of the Mac disk image, for `dmgbuild -s packaging/dmg_settings.py -D app=dist/Cairn.app Cairn Cairn.dmg`.
# dmgbuild writes the window settings itself, so it does not need Finder (which a build machine has no screen for).
import os

app = defines.get('app', 'dist/Cairn.app')     # noqa: F821  (`defines` is provided by dmgbuild)

format = 'UDZO'
files = [app]
symlinks = {'Applications': '/Applications'}
background = 'packaging/dmg-background.tiff'      # relative to the repo root, where the build runs (this file is exec'd, so it has no __file__)
window_rect = ((200, 140), (640, 420))
icon_size = 128
text_size = 14
icon_locations = {os.path.basename(app): (170, 200), 'Applications': (470, 200)}
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
default_view = 'icon-view'
