"""Regenerates the picture behind the icons in the Mac disk image: packaging/dmg-background.tiff (1x and 2x in one file).
Run after changing the look:  python3 packaging/make_dmg_background.py  (needs Playwright's Chromium and macOS `tiffutil`)."""
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
FONTS = (HERE.parent / 'site' / 'fonts').as_uri()
W, H = 640, 420
HTML = f"""<style>
@font-face {{ font-family: 'Bricolage Grotesque'; font-weight: 200 800; src: url('{FONTS}/bricolage-grotesque-latin.woff2'); }}
@font-face {{ font-family: 'Instrument Sans'; font-weight: 400 700; src: url('{FONTS}/instrument-sans-latin.woff2'); }}
body {{ margin: 0; width: {W}px; height: {H}px; background: linear-gradient(180deg, #eef5fd, #d4e5f7); position: relative; overflow: hidden; color: #0f2236; }}
h1 {{ font: 700 25px 'Bricolage Grotesque'; letter-spacing: -.02em; position: absolute; top: 44px; width: 100%; text-align: center; margin: 0; }}
p {{ font: 500 14px 'Instrument Sans'; position: absolute; top: 80px; width: 100%; text-align: center; margin: 0; color: #4d6177; }}
svg {{ position: absolute; left: 0; top: 0; }}
</style>
<h1>Drag Cairn onto Applications</h1><p>Then open it from there.</p>
<svg width="{W}" height="{H}"><path d="M 250 200 C 290 176 350 176 390 200" fill="none" stroke="#1f6fd0" stroke-width="4" stroke-linecap="round" stroke-dasharray="1 11"/>
<path d="M 378 187 L 392 201 L 373 207" fill="none" stroke="#1f6fd0" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/></svg>"""

with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
    html_file = Path(tmp) / 'bg.html'
    html_file.write_text(HTML)
    browser = p.chromium.launch()
    paths = []
    for scale, name in ((1, 'bg.png'), (2, 'bg@2x.png')):
        page = browser.new_page(viewport={'width': W, 'height': H}, device_scale_factor=scale)
        page.goto(html_file.as_uri())                          # from a file, so the local fonts are allowed to load
        page.wait_for_function('document.fonts.ready.then(() => true)')
        page.wait_for_timeout(300)
        page.screenshot(path=str(Path(tmp) / name))
        page.close()
        paths.append(str(Path(tmp) / name))
    browser.close()
    subprocess.run(['tiffutil', '-cathidpicheck', *paths, '-out', str(HERE / 'dmg-background.tiff')], check=True)
print('dmg background written')
