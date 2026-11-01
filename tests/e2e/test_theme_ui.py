"""Light and dark themes, through the real UI: following the system, remembering the choice, and that every screen is
actually readable in light (a scanner measures the contrast of all visible text and looks for leftover dark panels)."""
import pytest

from conftest import answer_dialogs, manual_dialogs

pytestmark = pytest.mark.e2e

AUDIT = """minRatio => {
  const freeze = document.createElement('style'); freeze.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}'; document.head.appendChild(freeze); document.body.offsetHeight;
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
    return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
  const over = (fg, bg) => ({r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1});
  const backdrop = el => { const chain = []; for (let e = el; e; e = e.parentElement) chain.push(e);
    let bg = {r: 255, g: 255, b: 255, a: 1};
    for (const e of chain.reverse()) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) bg = over(c, bg); }
    return bg; };
  const visible = el => { const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return false;
    let o = 1; for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden') return false; o *= parseFloat(s.opacity); }
    return o > 0.3; };
  const name = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + [...el.classList].slice(0, 3).map(c => '.' + c).join('');
  const problems = [], seen = new Set();
  const add = (kind, el, extra) => { const key = kind + name(el) + (extra.text || ''); if (seen.has(key) || problems.length > 30) return;
    seen.add(key); problems.push({kind, el: name(el), ...extra}); };
  for (const el of document.querySelectorAll('body *')) {
    if (['SCRIPT', 'STYLE', 'OPTION', 'OPTGROUP', 'SVG', 'PATH', 'NOSCRIPT'].includes(el.tagName.toUpperCase()) || !visible(el)) continue;
    const s = getComputedStyle(el), bg = backdrop(el);
    const ownText = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent.trim()).join(' ');
    const isField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) && (el.value || el.placeholder) && el.type !== 'checkbox' && el.type !== 'radio';
    if (ownText || isField) {
      const fg = parse(s.color); if (fg) { const ratio = (Math.max(lum(over(fg, bg)), lum(bg)) + .05) / (Math.min(lum(over(fg, bg)), lum(bg)) + .05);
        if (ratio < minRatio) add('contrast', el, {text: (ownText || el.value || el.placeholder).slice(0, 30), ratio: +ratio.toFixed(2)}); }
    }
    const own = parse(s.backgroundColor), r = el.getBoundingClientRect();
    if (document.documentElement.dataset.theme === 'light' && own && own.a > .9 && r.width * r.height > 3000 && lum(own) < 0.1)
      add('dark-panel', el, {text: s.backgroundColor, area: Math.round(r.width * r.height)});
  }
  freeze.remove();
  return problems;
}"""


@pytest.fixture(autouse=True)
def reset_theme(page):
    yield
    page.evaluate("fetch('/api/theme', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({theme: 'system'})})")
    page.evaluate("""async () => { const l = await (await fetch('/api/saved-queries')).json();
        for (const q of l.queries) await fetch('/api/saved-queries/' + q.id, {method: 'DELETE'}); }""")


def use(pg, theme):
    pg.evaluate("t => Theme.apply(t)", theme)


def theme_of(pg):
    return pg.evaluate("[document.documentElement.dataset.theme, document.documentElement.dataset.themePref]")


def audit(pg, min_ratio=3.0):
    return pg.evaluate(AUDIT, min_ratio)


# ---- behaviour ---------------------------------------------------------------------------------------------

def test_it_follows_the_operating_system_by_default(page):
    page.emulate_media(color_scheme='light')
    page.reload()
    assert theme_of(page) == ['light', 'system']
    page.emulate_media(color_scheme='dark')
    page.reload()
    assert theme_of(page) == ['dark', 'system']


def test_it_switches_live_when_the_system_does(page):
    page.emulate_media(color_scheme='dark')
    page.reload()
    page.emulate_media(color_scheme='light')
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")


def test_a_fixed_choice_ignores_the_system(page):
    page.click('#theme-btn')                                   # system -> light
    page.emulate_media(color_scheme='dark')
    assert theme_of(page) == ['light', 'light']


def test_the_button_cycles_and_the_choice_survives_a_reload(page):
    page.emulate_media(color_scheme='dark')
    page.reload()
    labels = [page.inner_text('#theme-btn')]
    for _ in range(3):
        page.click('#theme-btn')
        labels.append(page.inner_text('#theme-btn'))
    assert labels == ['◐ System', '☀ Light', '☾ Dark', '◐ System']
    page.click('#theme-btn')                                   # light, while the system is dark
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")
    page.reload()
    assert theme_of(page) == ['light', 'light'] and page.inner_text('#theme-btn') == '☀ Light'


def test_the_palette_can_change_it(connected):
    connected.keyboard.press('Meta+k')
    connected.fill('.palette-input', 'theme: light')
    connected.keyboard.press('Enter')
    connected.wait_for_function("document.documentElement.dataset.theme === 'light'")
    connected.keyboard.press('Meta+k')
    connected.fill('.palette-input', 'theme')
    labels = connected.locator('.palette-item .palette-label').all_inner_texts()
    assert 'Theme: light' not in labels and 'Theme: dark' in labels      # the current one is not offered


def test_the_page_really_is_light(page):
    use(page, 'light')
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert bg == 'rgb(255, 255, 255)'
    assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == 'light'


# ---- every screen is readable ------------------------------------------------------------------------------

def open_table(pg, name):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


def run_sql(pg, sql):
    pg.click('#new-query-tab-btn')
    pg.wait_for_selector('.tab-content.active .CodeMirror')
    pg.evaluate("sql => document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue(sql)", sql)
    pg.click('.tab-content.active [data-action=execute]')
    pg.wait_for_selector('.tab-content.active .results-grid table, .tab-content.active .results-grid .error-message')


def screens(pg):
    """Yield (name) after putting the UI into each state; the caller audits it. Cleans up between states."""
    yield 'welcome and connected sidebar'
    open_table(pg, 'customers')
    yield 'a table grid'
    cell = pg.locator('.tab-content.active tr[data-row-index="0"] td[data-column=name]')
    cell.click(); pg.keyboard.press('ControlOrMeta+A'); pg.keyboard.type('Edited'); pg.keyboard.press('Tab')
    pg.click('.tab-content.active [data-action=add-row]')
    yield 'a grid with an edited cell and a new row'
    th = pg.locator('.tab-content.active th[data-col="name"]')
    th.hover(); th.locator('.th-insight').click()
    pg.wait_for_selector('.insight .insight-facts')
    yield 'column insights'
    pg.keyboard.press('Escape')
    run_sql(pg, 'select id, name, email from customers')
    yield 'a query and its results'
    run_sql(pg, 'select * from no_such_table')
    yield 'a query error'
    pg.click('#open-map-btn')
    pg.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    yield 'the schema map'
    pg.keyboard.press('Escape')
    pg.keyboard.press('Meta+k')
    pg.wait_for_selector('.palette-input')
    yield 'the command palette'
    pg.keyboard.press('Escape')
    pg.click('#manage-connections-btn')
    yield 'the connections manager'
    pg.click('#new-connection-btn-manager')
    yield 'the connection form'
    pg.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    pg.click('#new-query-tab-btn')
    pg.wait_for_selector('.tab-content.active [data-action=ask]')
    pg.click('.tab-content.active [data-action=ask]')
    pg.wait_for_selector('#ai-settings-modal.active')
    yield 'the assistant settings'
    pg.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    pg.evaluate("""fetch('/api/saved-queries', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: 'Top customers', sql: 'select * from customers\\nlimit 10', connection_name: 'Demo shop'})}).then(() => app.savedQueries.load())""")
    pg.click('#new-query-tab-btn')
    pg.wait_for_selector('.tab-content.active .CodeMirror')
    pg.click('.tab-content.active [data-action=saved-queries]')
    pg.wait_for_selector('#saved-queries-list .saved-item')
    yield 'the saved queries list'
    pg.keyboard.press('Escape')
    pg.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue('select 1')")
    manual_dialogs(pg)
    pg.click('.tab-content.active [data-action=save-query]')
    pg.wait_for_selector('.app-dialog-input')
    pg.click('.app-dialog [data-answer=ok]')                 # empty name: shows the inline error
    pg.wait_for_selector('.app-dialog-error', state='visible')
    yield 'the name prompt with its error'
    pg.keyboard.press('Escape')
    pg.wait_for_selector('.app-dialog', state='detached')
    import os, tempfile
    folder = tempfile.mkdtemp()
    open_table(pg, 'orders')
    for label, text, check in [('the CSV import dialog with an error', 'id,status,total\n9001,paid,5\n1,paid,7\n', True),
                               ('the CSV import dialog with warnings', 'order status,amount\npaid,5\nlate\n', False)]:
        path = os.path.join(folder, 'people.csv')
        with open(path, 'w') as f:
            f.write(text)
        with pg.expect_file_chooser() as chooser:
            pg.click('.tab-content.active [data-action=import-csv]')
        chooser.value.set_files(path)
        pg.wait_for_selector('#import-modal.active .import-mapping')
        if check:
            pg.click('#import-check')
            pg.wait_for_selector('#import-status.error')
        yield label
        pg.click('#import-cancel')
        pg.wait_for_selector('#import-modal.active', state='hidden')
    pg.click('#new-query-tab-btn')
    pg.wait_for_selector('.tab-content.active .CodeMirror')
    pg.evaluate("document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue('drop table customers')")
    manual_dialogs(pg)
    pg.click('.tab-content.active [data-action=execute]')
    pg.wait_for_selector('.app-dialog')
    yield 'the confirm dialog'
    pg.keyboard.press('Enter')
    pg.wait_for_selector('.app-dialog', state='detached')
    pg.evaluate("ui.notify('Saved 2 changes.', 'success'); ui.notify('Nothing was saved. Change 2 of 3 failed.', 'error')")
    pg.wait_for_selector('#toast-stack .notification')
    yield 'toasts'


def collect(pg, theme):
    use(pg, theme)
    found = {}
    pg.evaluate("window.__dialogs = []")
    answer_dialogs(pg, False)
    for state in screens(pg):
        use(pg, theme)
        issues = audit(pg, 3.0 if theme == 'light' else 2.5)
        if issues:
            found[state] = issues
    return found


def report(found):
    return '\n'.join(f'{state}: ' + '; '.join(f"{i['kind']} {i['el']} {i.get('text', '')} {i.get('ratio', '')}" for i in issues[:8])
                     for state, issues in found.items())


def test_dark_is_clean_so_the_scanner_is_not_just_noise(connected):
    found = collect(connected, 'dark')
    assert not found, 'the scanner flags the existing dark theme, so its threshold is wrong:\n' + report(found)


def test_every_screen_is_readable_in_light(connected):
    found = collect(connected, 'light')
    assert not found, 'unreadable text or leftover dark panels in light:\n' + report(found)


def test_production_banner_and_environment_colours_are_readable_in_light(connected):
    connected.evaluate("document.body.dataset.env = 'production'")
    use(connected, 'light')
    found = {'production': audit(connected)} if audit(connected) else {}
    assert not found, report(found)
