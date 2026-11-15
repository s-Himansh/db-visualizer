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
    {'name': 'Cairn-macOS-AppleSilicon.dmg', 'size': 70 * 1048576, 'browser_download_url': 'https://example.test/arm.zip'},
    {'name': 'Cairn-Windows.zip', 'size': 90 * 1048576, 'browser_download_url': 'https://example.test/win.zip'}]}


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
    assert pg.get_attribute('#get-btn', 'href').endswith('/releases/latest/download/Cairn-macOS-AppleSilicon.dmg')
    assert 'Windows' in pg.inner_text('#other')


def test_a_mac_whose_browser_reports_an_intel_chip_gets_the_intel_build(browser):
    pg = open_page(browser, MAC, chip='x86')
    pg.wait_for_function("document.getElementById('get-label').textContent === 'Download for macOS (Intel)'")
    assert pg.get_attribute('#get-btn', 'href').endswith('/Cairn-macOS-Intel.dmg')
    assert 'Apple Silicon' in pg.inner_text('#other')


def test_windows_gets_the_windows_build(browser):
    pg = open_page(browser, WIN)
    pg.wait_for_function("document.getElementById('get-label').textContent === 'Download for Windows'")
    assert pg.get_attribute('#get-btn', 'href').endswith('/Cairn-Windows.zip')


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
    assert pg.get_attribute('a[data-dl=mac-intel]', 'href').endswith('/releases/latest/download/Cairn-macOS-Intel.dmg')   # and keeps its fallback


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


def test_the_pop_up_warning_is_seen_before_scrolling_and_its_links_work(browser):
    pg = open_page(browser, MAC)
    box = pg.locator('.heads-up').bounding_box()
    assert box['y'] + box['height'] < 900, box                                # on the first screen, not at the bottom
    assert 'pop-up' in pg.inner_text('.heads-up')
    pg.click('.heads-up a[href="#source"]')
    pg.wait_for_function("(() => { const r = document.getElementById('source').getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight; })()")
    assert './run.sh' in pg.inner_text('#source ~ .launch')
    pg.click('.heads-up a[href="#first-launch"]') if pg.locator('.heads-up a[href="#first-launch"]').is_visible() else pg.evaluate("location.hash = '#first-launch'")
    pg.wait_for_function("(() => { const r = document.getElementById('first-launch').getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight; })()")


def test_the_code_blocks_scroll_instead_of_breaking_a_phone_layout(browser):
    pg = open_page(browser, MAC, width=360)
    pg.wait_for_load_state('load')
    assert pg.evaluate('document.documentElement.scrollWidth') <= 360
    assert pg.locator('#source ~ .launch pre').count() == 2


def demo_page(browser):
    pg = open_page(browser, MAC)
    pg.wait_for_selector('#demo-orders tr')
    return pg


def test_the_demo_arrow_jumps_to_the_customer_and_says_who_points_at_them(browser):
    pg = demo_page(browser)
    pg.click('#demo-orders tr[data-order="101"] .link')                          # order 101 belongs to customer 3
    assert 'target' in pg.get_attribute('#demo-customers tr[data-customer-row="3"]', 'class')
    assert 'Aiko Mori' in pg.inner_text('#demo-live') and '2 orders point' in pg.inner_text('#demo-live')   # orders 101 and 104
    pg.click('#demo-orders tr[data-order="102"] .link')                          # moves on: only one row is the target
    assert pg.locator('#demo-customers .target').count() == 1
    assert '1 order points' in pg.inner_text('#demo-live')


def edit_total(pg, order, text):
    cell = pg.locator(f'[data-total="{order}"]')
    cell.click(); pg.keyboard.press('ControlOrMeta+a'); pg.keyboard.type(text); pg.keyboard.press('Enter')


def test_editing_a_demo_total_raises_the_bar_and_undo_puts_it_back(browser):
    pg = demo_page(browser)
    assert pg.is_hidden('#demo-bar')
    edit_total(pg, 102, '99')
    assert pg.is_visible('#demo-bar') and pg.inner_text('#demo-count') == '1 unsaved change'
    assert pg.inner_text('[data-total="102"]') == '99.00' and 'changed' in pg.get_attribute('[data-total="102"]', 'class')
    edit_total(pg, 105, '10')
    assert pg.inner_text('#demo-count') == '2 unsaved changes'
    pg.click('#demo-undo')
    assert pg.is_hidden('#demo-bar') and pg.inner_text('[data-total="102"]') == '120.50' and pg.inner_text('[data-total="105"]') == '310.00'


def test_saving_in_the_demo_keeps_the_values_and_hides_the_bar(browser):
    pg = demo_page(browser)
    edit_total(pg, 103, '25.5')
    pg.click('#demo-save')
    assert pg.is_hidden('#demo-bar') and pg.inner_text('[data-total="103"]') == '25.50'
    assert 'changed' not in (pg.get_attribute('[data-total="103"]', 'class') or '')
    assert 'Saved 1 change' in pg.inner_text('#demo-live')
    edit_total(pg, 103, '25.50')                                                 # typing the saved value again is not a change
    assert pg.is_hidden('#demo-bar')


def test_the_demo_refuses_text_where_a_number_belongs(browser):
    pg = demo_page(browser)
    edit_total(pg, 101, 'lots')
    assert pg.inner_text('[data-total="101"]') == '48.00' and pg.is_hidden('#demo-bar')


def test_the_demo_arrows_work_from_the_keyboard(browser):
    pg = demo_page(browser)
    pg.focus('#demo-orders tr[data-order="104"] .link'); pg.keyboard.press('Enter')
    assert 'target' in pg.get_attribute('#demo-customers tr[data-customer-row="3"]', 'class')
