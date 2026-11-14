"""The bundled typefaces really load and land on the right text, with no request leaving the app."""
import pytest

pytestmark = pytest.mark.e2e


def test_the_three_typefaces_load_and_apply(page):
    page.wait_for_function("document.fonts.load('400 14px \"Instrument Sans\"').then(f => f.length > 0)")
    assert page.evaluate("document.fonts.check('600 14px \"Instrument Sans\"')")
    assert page.evaluate("document.fonts.load('700 24px \"Bricolage Grotesque\"').then(f => f.length > 0)")
    assert page.evaluate("document.fonts.load('400 13px \"Geist Mono\"').then(f => f.length > 0)")
    family = lambda sel: page.evaluate("s => getComputedStyle(document.querySelector(s)).fontFamily", sel)
    assert family('body').startswith('"Instrument Sans"')
    assert family('.sidebar-header h2').startswith('"Bricolage Grotesque"')
    assert family('#welcome h2').startswith('"Bricolage Grotesque"')


def test_grid_data_is_in_the_monospace_face(connected):
    connected.locator('#tables-content .tree-item').filter(has=connected.locator('.tree-label:text-is("customers")')).click()
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')
    connected.wait_for_function("document.fonts.load('400 13px \"Geist Mono\"').then(f => f.length > 0)")
    assert connected.evaluate("getComputedStyle(document.querySelector('.tab-content.active .data-table td')).fontFamily").startswith('"Geist Mono"')


def test_nothing_is_requested_from_outside_the_app(browser, server):
    ctx = browser.new_context()
    pg = ctx.new_page()
    hosts = set()
    pg.on('request', lambda r: hosts.add(r.url.split('/')[2]) if r.url.startswith('http') else None)
    pg.goto(server)
    pg.wait_for_selector('#manage-connections-btn')
    pg.evaluate("document.fonts.ready")
    pg.wait_for_timeout(500)
    ctx.close()
    assert hosts == {server.split('/')[2]}, hosts


def test_the_accented_part_of_a_font_is_fetched_only_when_a_name_needs_it(page):
    page.evaluate("""() => { const d = document.createElement('div'); d.id = 'probe'; d.style.cssText = 'font:600 14px "Instrument Sans"';
        d.textContent = 'Łódź'; document.body.appendChild(d); }""")
    page.wait_for_function("document.fonts.load('600 14px \"Instrument Sans\"', 'Łódź').then(f => f.some(x => x.unicodeRange.includes('0100')))")
