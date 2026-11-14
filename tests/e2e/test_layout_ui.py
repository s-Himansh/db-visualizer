"""The sidebar names the connection you are in: its colour, name, environment and where it points."""
import pytest

from conftest import connect

pytestmark = pytest.mark.e2e


def add(pg, name, env='', database='x.db'):
    pg.evaluate("""async c => (await fetch('/api/connections', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(c)})).json()""", dict(name=name, type='sqlite', database=database, environment=env))


def test_nothing_is_shown_until_a_connection_is_open(page):
    assert page.is_hidden('#side-identity')


def test_the_sidebar_names_the_connection_and_where_it_points(connected):
    assert connected.is_visible('#side-identity')
    assert connected.inner_text('#side-name') == 'Demo shop'
    assert connected.inner_text('#side-where') == 'demo.db'
    assert connected.inner_text('#side-avatar') == 'DS'


def test_it_shows_the_environment_and_follows_a_switch(connected):
    add(connected, 'Prod copy', 'production', connected.demo_db)
    connected.evaluate("app.connectionManager.loadConnections()")
    connected.wait_for_function("app.connectionManager.connections.length === 2")
    connected.click('#manage-connections-btn')
    connected.click('.connection-item:has-text("Prod copy") .connect-btn')
    connected.wait_for_function("document.getElementById('side-name').textContent === 'Prod copy'")
    assert 'production' in connected.inner_text('#side-env').lower()
    connected.keyboard.press('ControlOrMeta+1')                 # back to the first connection
    connected.wait_for_function("document.getElementById('side-name').textContent === 'Demo shop'")
    assert connected.inner_text('#side-env').strip() == ''


def test_the_avatar_wears_the_connections_own_colour(connected):
    expected = connected.evaluate("""() => { const h = Theme.hueOf(app.connectionManager.activeConnection);
        const probe = document.createElement('i'); probe.style.color = `hsl(${h} 77% 51%)`; document.body.appendChild(probe);
        const c = getComputedStyle(probe).color; probe.remove(); return c; }""")
    assert connected.evaluate("getComputedStyle(document.getElementById('side-avatar')).backgroundColor") == expected


def test_a_hostile_name_stays_text_in_the_sidebar(page):
    boom = '<img src=x onerror="window.__xss=1">'
    add(page, boom, 'staging', page.demo_db)
    page.reload()
    page.wait_for_selector('.conn-tile')
    page.click('.conn-tile')
    page.wait_for_selector('#tables-content .tree-item')
    assert page.inner_text('#side-name') == boom and page.locator('#side-identity img').count() == 0
    assert not page.evaluate('window.__xss')
