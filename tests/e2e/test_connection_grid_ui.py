"""Picking a database when there are many: every connection on one grid, grouped, searchable, keyboard friendly."""
import json
import sqlite3

import pytest

from conftest import connect

pytestmark = pytest.mark.e2e

ENVS = ['production', 'staging', 'development', 'local', '']


def add(pg, name, type_='mysql', env='', database='shop', host='db.example.com', port=3306, **extra):
    pg.evaluate("""async c => (await fetch('/api/connections', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(c)})).json()""", dict(name=name, type=type_, host=host, port=port, database=database, environment=env,
                                                   username='u', password='p', **extra))


@pytest.fixture
def many(page):
    for i in range(30):
        add(page, f'db-{i:02d}', ['mysql', 'postgresql', 'oracle'][i % 3], ENVS[i % 5], database=f'app{i}')
    page.reload()
    page.wait_for_selector('.conn-tile')
    return page


def names(pg, scope='#welcome'):
    return pg.locator(f'{scope} .conn-tile .connection-name').all_inner_texts()


def test_every_connection_is_on_the_page_in_groups_with_counts(many):
    assert len(names(many)) == 30
    heads = many.locator('#welcome .conn-group-head').evaluate_all('els => els.map(e => [e.children[1].textContent, e.children[2].textContent])')
    assert [h[0] for h in heads] == ['Production', 'Staging', 'Development', 'Local', 'Not tagged']
    assert all(h[1] == '6' for h in heads)


def test_tiles_use_the_width_so_many_fit_on_screen(many):
    boxes = many.locator('#welcome .conn-tile').evaluate_all('els => els.map(e => { const r = e.getBoundingClientRect(); return [r.left, r.top]; })')
    per_row = len([b for b in boxes if abs(b[1] - boxes[0][1]) < 4])
    assert per_row >= 3, f'only {per_row} tiles in a row'


def test_a_tile_says_where_it_points_so_equal_names_can_be_told_apart(page):
    add(page, 'same', 'mysql', 'production', database='billing', host='a.example.com')
    add(page, 'same', 'mysql', 'production', database='orders', host='b.example.com')
    page.reload()
    page.wait_for_selector('.conn-tile')
    where = page.locator('#welcome .conn-where').all_inner_texts()
    assert sorted(where) == ['a.example.com:3306 / billing', 'b.example.com:3306 / orders']


def test_search_filters_by_name_type_host_and_environment_and_says_when_nothing_matches(many):
    box = many.locator('#welcome .conn-search')
    box.fill('db-07')
    assert names(many) == ['db-07']
    box.fill('oracle')
    assert len(names(many)) == 10
    box.fill('production')
    assert len(names(many)) == 6
    box.fill('zzz-nothing')
    assert 'Nothing matches' in many.inner_text('#welcome')
    box.fill('')
    assert len(names(many)) == 30


def test_a_group_can_be_collapsed(many):
    many.click('#welcome .conn-group-head:has-text("Local")')
    assert len(names(many)) == 24
    many.click('#welcome .conn-group-head:has-text("Local")')
    assert len(names(many)) == 30


def test_slash_jumps_to_search_and_arrows_and_enter_open_a_connection(page, demo_db):
    sqlite3.connect(demo_db).close()
    add(page, 'Demo shop', 'sqlite', 'local', database=demo_db, host=None, port=None)
    add(page, 'Other', 'sqlite', 'local', database=demo_db, host=None, port=None)
    page.reload()
    page.wait_for_selector('.conn-tile')
    page.click('body', position={'x': 5, 'y': 400})
    page.keyboard.press('/')
    assert page.evaluate("document.activeElement.classList.contains('conn-search')")
    page.keyboard.type('demo')
    page.keyboard.press('ArrowDown')
    assert page.evaluate("document.activeElement.classList.contains('conn-tile')")
    page.keyboard.press('Enter')
    page.wait_for_selector('#tables-content .tree-item')
    assert 'Demo shop' in page.inner_text('#top-bar, body')


def test_open_connections_are_listed_first_and_marked(page, demo_db):
    add(page, 'Aaa other', 'sqlite', 'production', database=demo_db, host=None, port=None)
    add(page, 'Zzz demo', 'sqlite', 'local', database=demo_db, host=None, port=None)
    page.reload()
    page.click('#manage-connections-btn')
    page.click('.connection-item:has-text("Zzz demo") .connect-btn')
    page.wait_for_selector('#tables-content .tree-item')
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    page.click('#manage-connections-btn')
    heads = page.locator('#connections-manager-modal .conn-group-head').evaluate_all('els => els.map(e => e.children[1].textContent)')
    assert heads[0] == 'Open now'
    assert page.locator('#connections-manager-modal .conn-group').first.locator('.conn-dot').count() == 1


def test_the_last_one_you_opened_comes_first_within_its_group(page, demo_db):
    for name in ('Aaa', 'Bbb', 'Ccc'):
        add(page, name, 'sqlite', 'local', database=demo_db, host=None, port=None)
    page.reload()
    page.click('#manage-connections-btn')
    page.click('.connection-item:has-text("Ccc") .connect-btn')
    page.wait_for_selector('#tables-content .tree-item')
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    page.click('#manage-connections-btn')                                   # the window closed on connect: reopen it
    page.click('.connection-item:has-text("Ccc") .connect-btn')            # and disconnect again
    page.wait_for_selector('.connection-item:has-text("Ccc") .connect-btn:text-is("Connect")')
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    page.reload()
    page.click('#manage-connections-btn')
    assert page.locator('#connections-manager-modal .conn-tile .connection-name').all_inner_texts()[0] == 'Ccc'


def test_names_and_addresses_stay_text(page):
    boom = '<img src=x onerror="window.__xss=1">'
    add(page, boom, 'mysql', 'production', database='x" onmouseover="window.__xss=2', host=boom)
    page.reload()
    page.wait_for_selector('.conn-tile')
    page.hover('.conn-tile')
    page.wait_for_timeout(300)
    assert not page.evaluate('window.__xss')                 # nothing ran (the page was reloaded, so it is unset)
    assert page.locator('#welcome img').count() == 0
    assert boom in page.inner_text('#welcome .connection-name')
