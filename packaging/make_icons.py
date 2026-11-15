"""Regenerates the app icons from cairn.svg: cairn.icns (macOS, needs `iconutil`) and cairn.ico (Windows), plus the
page's copy of the logo. Run it after the logo changes:  python3 packaging/make_icons.py  (needs Playwright's Chromium)."""
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SVG = (HERE / 'cairn.svg').read_text()


def render(browser, size):
    page = browser.new_page(viewport={'width': size, 'height': size}, device_scale_factor=1)
    page.set_content(f'<body style="margin:0;background:transparent"><div style="width:{size}px;height:{size}px">{SVG.replace("<svg ", f"<svg width={chr(34)}{size}{chr(34)} height={chr(34)}{size}{chr(34)} ", 1)}</div></body>')
    png = page.screenshot(omit_background=True, clip={'x': 0, 'y': 0, 'width': size, 'height': size})
    page.close()
    return png


def make_ico(pngs, path):
    sizes = sorted(pngs)
    head = struct.pack('<HHH', 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, blobs = b'', b''
    for s in sizes:
        data = pngs[s]
        entries += struct.pack('<BBBBHHII', s % 256, s % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    path.write_bytes(head + entries + blobs)


with sync_playwright() as p:
    browser = p.chromium.launch()
    want = {16, 32, 48, 64, 128, 256, 512, 1024}
    pngs = {s: render(browser, s) for s in want}
    browser.close()

make_ico({s: pngs[s] for s in (16, 32, 48, 64, 128, 256)}, HERE / 'cairn.ico')
with tempfile.TemporaryDirectory() as tmp:
    iconset = Path(tmp) / 'cairn.iconset'
    iconset.mkdir()
    for name, size in {'icon_16x16': 16, 'icon_16x16@2x': 32, 'icon_32x32': 32, 'icon_32x32@2x': 64, 'icon_128x128': 128,
                       'icon_128x128@2x': 256, 'icon_256x256': 256, 'icon_256x256@2x': 512, 'icon_512x512': 512, 'icon_512x512@2x': 1024}.items():
        (iconset / f'{name}.png').write_bytes(pngs[size])
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(HERE / 'cairn.icns')], check=True)
shutil.copy(HERE / 'cairn.svg', HERE.parent / 'site' / 'img' / 'cairn.svg')
(HERE.parent / 'site' / 'img' / 'cairn-512.png').write_bytes(pngs[512])
(HERE.parent / 'static' / 'cairn.png').write_bytes(pngs[256])        # the window icon on Linux
print('icons written')
