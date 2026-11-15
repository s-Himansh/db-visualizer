"""The download page in a real browser: the right build for each visitor, and nothing breaks on a phone."""
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e
URL = (Path(__file__).resolve().parent.parent.parent / 'site' / 'index.html').as_uri()
MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'
WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
LINUX = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
PHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
RELEASE = {'tag_name': 'v1.2.3', 'assets': [
    {'name': 'DB-Visualizer-macOS-AppleSilicon.zip', 'size': 70 * 1048576, 'browser_download_url': 'https://example.test/arm.zip'},
    {'name': 'DB-Visualizer-Windows.zip', 'size': 90 * 1048576, 'browser_download_url': 'https://example.test/win.zip'}]}


def open_page(browser, ua, release=None, width=1280, chip=None):
    """chip: what the browser says about the processor. None is Safari (says nothing); 'arm' or 'x86' is Chrome or Edge."""
    ctx = browser.new_context(user_agent=ua, viewport={'width': width, 'height': 900})
    hint = 'undefined' if chip is None else "{getHighEntropyValues: async () => ({architecture: '%s'})}" % chip
    ctx.add_init_script(f"Object.defineProperty(navigator, 'userAgentData', {{value: {hint}, configurable: true}})")
    pg = ctx.new_page()
    if release is None:
        pg.route('https://api.github.com/**', lambda r: r.abort())
    else:
        pg.route('https://api.github.com/**', lambda r: r.fulfill(status=200, content_type='application/json', body=json.dumps(release)))
    pg.goto(URL)
    return pg


def test_a_mac_gets_the_mac_build(browser):
    pg = open_page(browser, MAC)
    pg.wait_for_function("document.getElementById('get-label').textContent === 'Download for macOS'")
    assert pg.get_attribute('#get-btn', 'href').endswith('/releases/latest/download/DB-Visualizer-macOS-AppleSilicon.zip')
    assert 'Windows' in pg.inner_text('#other')


def test_a_mac_whose_browser_reports_an_intel_chip_gets_the_intel_build(browser):
    pg = open_page(browser, MAC, chip='x86')
    pg.wait_for_function("document.getElementById('get-label').textContent === 'Download for macOS (Intel)'")
    assert pg.get_attribute('#get-btn', 'href').endswith('/DB-Visualizer-macOS-Intel.zip')
    assert 'Apple Silicon' in pg.inner_text('#other')


def test_windows_gets_the_windows_build(browser):
    pg = open_page(browser, WIN)
    pg.wait_for_function("document.getElementById('get-label').textContent === 'Download for Windows'")
    assert pg.get_attribute('#get-btn', 'href').endswith('/DB-Visualizer-Windows.zip')


def test_linux_and_phones_are_told_the_truth_instead_of_getting_a_wrong_file(browser):
    linux = open_page(browser, LINUX)
    linux.wait_for_function("document.getElementById('get-label').textContent === 'See the downloads'")
    assert 'no Linux build' in linux.inner_text('#get-note')
    assert linux.get_attribute('#get-btn', 'href') == '#download'
    phone = open_page(browser, PHONE)
    phone.wait_for_function("document.getElementById('get-label').textContent === 'See the downloads'")
    assert 'desktop app' in phone.inner_text('#get-note')


def test_the_version_sizes_and_exact_links_come_from_the_latest_release(browser):
    pg = open_page(browser, MAC, RELEASE)
    pg.wait_for_function("document.getElementById('version').textContent === 'v1.2.3'")
    assert pg.get_attribute('#get-btn', 'href') == 'https://example.test/arm.zip'
    assert pg.get_attribute('a[data-dl=win]', 'href') == 'https://example.test/win.zip'
    assert pg.inner_text('[data-size=win]') == '(90 MB)'
    assert pg.inner_text('[data-size=mac-intel]') == ''                      # a build the release doesn't have shows no size
    assert pg.get_attribute('a[data-dl=mac-intel]', 'href').endswith('/releases/latest/download/DB-Visualizer-macOS-Intel.zip')   # and keeps its fallback


def test_the_page_works_when_github_cannot_be_reached(browser):
    pg = open_page(browser, WIN)
    pg.wait_for_function("document.getElementById('get-label').textContent === 'Download for Windows'")
    pg.wait_for_timeout(300)
    assert pg.inner_text('#version') == ''
    assert pg.get_attribute('#get-btn', 'href').startswith('https://github.com/')


@pytest.mark.parametrize('width', [390, 820, 1440])
def test_nothing_scrolls_sideways(browser, width):
    pg = open_page(browser, MAC, width=width)
    pg.wait_for_load_state('load')
    assert pg.evaluate('document.documentElement.scrollWidth') <= width


def test_the_page_follows_the_system_theme_and_swaps_its_screenshots(browser):
    for scheme, bg in (('light', 'rgb(234, 243, 252)'), ('dark', 'rgb(11, 11, 13)')):
        ctx = browser.new_context(color_scheme=scheme, user_agent=MAC)
        pg = ctx.new_page(); pg.route('https://api.github.com/**', lambda r: r.abort()); pg.goto(URL)
        assert pg.evaluate('getComputedStyle(document.body).backgroundColor') == bg
        shot = pg.evaluate("document.querySelector('.hero picture img').currentSrc")
        assert shot.endswith('grid-sky.png' if scheme == 'light' else 'grid-obsidian.png')
