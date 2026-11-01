"""Finding relationships a database never declared, through the real UI."""
import sqlite3

import pytest

from conftest import connect

pytestmark = pytest.mark.e2e


def build(path, extra=''):
    c = sqlite3.connect(path)
    c.executescript("""
        create table customers(id integer primary key, name text);
        create table orders(id integer primary key, customer_id integer, status_id integer);
        create table items(id integer primary key, order_id integer);
        create table reviews(id integer primary key, customer_id integer);
        create table payments(id integer primary key, order_id integer);
    """ + extra)
    c.executemany('insert into customers values(?,?)', [(i, f'c{i}') for i in range(1, 41)])
    c.executemany('insert into orders values(?,?,?)', [(i, i % 40 + 1, 1) for i in range(1, 101)])
    c.executemany('insert into items values(?,?)', [(i, i % 100 + 1) for i in range(1, 201)])
    c.executemany('insert into reviews values(?,?)', [(i, (i % 40 + 1) if i % 10 else 900 + i) for i in range(1, 81)])
    c.executemany('insert into payments values(?,?)', [(i, 7000 + i) for i in range(1, 20)])
    c.commit()
    c.close()


@pytest.fixture
def loose(page, tmp_path):
    """A connected database with no foreign keys at all."""
    path = str(tmp_path / 'loose.db')
    build(path)
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'sqlite')
    page.fill('input[name=name]', 'Loose')
    page.fill('input[name=database]', path)
    page.click('#connection-form button[type=submit]')
    page.wait_for_selector('.connection-item:has-text("Loose")')
    connect(page, 'Loose')
    page.path = path
    return page


def open_map(pg):
    pg.click('#open-map-btn')
    pg.wait_for_selector('.tab-content.active .map-container')
    pg.wait_for_function("document.querySelector('.tab-content.active .map-info').textContent.length > 0")


def find(pg):
    pg.click('.tab-content.active [data-map=find]')
    pg.wait_for_selector('.tab-content.active .map-suggest-list')


def items(pg):
    return pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('.tab-content.active .map-suggest-item')]
        .map(i => [i.dataset.relation, {title: i.querySelector('.map-suggest-title').textContent, evidence: i.querySelector('.map-suggest-evidence').textContent,
                   confidence: i.querySelector('.map-suggest-confidence').textContent}]))""")


def decide(pg, relation, act):
    pg.locator(f'.tab-content.active .map-suggest-item[data-relation="{relation}"] [data-act={act}]').click()


# ---- finding ---------------------------------------------------------------------------------------------------------

def test_a_database_with_no_keys_offers_to_find_them_and_shows_the_evidence(loose):
    open_map(loose)
    assert 'No foreign keys found' in loose.inner_text('.tab-content.active .map-canvas')
    loose.click('.tab-content.active [data-map=find-empty]')
    loose.wait_for_selector('.tab-content.active .map-suggest-list')
    got = items(loose)
    assert set(got) == {'orders.customer_id', 'items.order_id', 'reviews.customer_id'}
    assert got['orders.customer_id']['title'].startswith('orders.customer_id → customers.id')
    assert 'All 40 distinct values in orders.customer_id exist in customers.id.' in got['orders.customer_id']['evidence']
    assert got['orders.customer_id']['confidence'] == 'high'
    assert 'point' in got['reviews.customer_id']['evidence'] and 'at nothing' in got['reviews.customer_id']['evidence']
    assert got['reviews.customer_id']['confidence'] == 'low'


def test_a_name_that_fits_but_data_that_does_not_is_not_offered(loose):
    open_map(loose)
    find(loose)
    assert 'payments.order_id' not in items(loose) and 'orders.status_id' not in items(loose)


def test_the_panel_explains_that_nothing_changes_in_the_database(loose):
    open_map(loose)
    find(loose)
    assert 'Your database is not changed' in loose.inner_text('.tab-content.active .map-suggest')


def test_looking_changes_nothing_on_the_map(loose):
    open_map(loose)
    find(loose)
    assert loose.locator('.tab-content.active .map-edge').count() == 0
    assert 'No foreign keys found' in loose.inner_text('.tab-content.active .map-canvas')


def test_a_database_that_already_declares_its_keys_has_nothing_new(connected):
    open_map(connected)
    connected.click('.tab-content.active [data-map=find]')
    connected.wait_for_selector('.tab-content.active .map-suggest-summary')
    assert 'Nothing new' in connected.inner_text('.tab-content.active .map-suggest')
    assert connected.locator('.tab-content.active .map-suggest-item').count() == 0


def test_the_panel_closes(loose):
    open_map(loose)
    find(loose)
    loose.click('.tab-content.active .map-suggest-head .btn')
    assert not loose.is_visible('.tab-content.active .map-suggest')
    loose.click('.tab-content.active [data-map=find]')
    loose.wait_for_selector('.tab-content.active .map-suggest-list')


# ---- accepting ------------------------------------------------------------------------------------------------------------

def test_accepting_draws_a_dashed_edge_and_removes_the_suggestion(loose):
    open_map(loose)
    find(loose)
    decide(loose, 'orders.customer_id', 'accept')
    loose.wait_for_selector('.tab-content.active .map-edge.is-inferred', state='attached')
    loose.wait_for_function("!document.querySelector('.tab-content.active .map-suggest-item[data-relation=\"orders.customer_id\"]')")
    assert loose.locator('.tab-content.active .map-edge.is-inferred').count() == 1
    assert '1 inferred' in loose.inner_text('.tab-content.active .map-info')
    assert 'Accepted by you (1)' in loose.inner_text('.tab-content.active .map-suggest-decided')
    assert loose.inner_text('.tab-content.active .map-edge title') if False else True
    title = loose.evaluate("document.querySelector('.tab-content.active .map-edge.is-inferred title').textContent")
    assert 'orders.customer_id → customers.id' in title and 'inferred' in title


def test_an_accepted_relationship_gives_the_grid_its_arrows(loose):
    open_map(loose)
    find(loose)
    decide(loose, 'orders.customer_id', 'accept')
    loose.wait_for_selector('.tab-content.active .map-edge.is-inferred', state='attached')
    loose.locator('#tables-content .tree-item').filter(has=loose.locator('.tree-label:text-is("orders")')).click()
    loose.wait_for_selector('.tab-content.active .data-table td.fk[data-column=customer_id]')
    loose.locator('.tab-content.active .data-table td.fk[data-column=customer_id]').first.click(modifiers=['Meta'])
    loose.wait_for_selector('.tab-content.active .filter-chip:visible')
    assert 'customers' in loose.inner_text('.tab-content.active .table-toolbar')


def test_accepted_relationships_survive_a_reload(loose):
    open_map(loose)
    find(loose)
    decide(loose, 'items.order_id', 'accept')
    loose.wait_for_selector('.tab-content.active .map-edge.is-inferred', state='attached')
    loose.reload()
    loose.wait_for_selector('#manage-connections-btn')
    loose.click('#manage-connections-btn')
    loose.click('.connection-item:has-text("Loose") .connect-btn')
    loose.wait_for_selector('#tables-content .tree-item')
    loose.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    open_map(loose)
    loose.wait_for_selector('.tab-content.active .map-edge.is-inferred', state='attached')


def test_forgetting_removes_the_edge_and_brings_the_suggestion_back(loose):
    open_map(loose)
    find(loose)
    decide(loose, 'orders.customer_id', 'accept')
    loose.wait_for_selector('.tab-content.active .map-edge.is-inferred', state='attached')
    loose.click('.tab-content.active .map-suggest-decided summary')
    loose.click('.tab-content.active .map-suggest-decided [data-act=forget]')
    loose.wait_for_selector('.tab-content.active .map-suggest-item[data-relation="orders.customer_id"]')
    assert loose.locator('.tab-content.active .map-edge.is-inferred').count() == 0


# ---- ignoring -----------------------------------------------------------------------------------------------------------------

def test_an_ignored_suggestion_does_not_come_back(loose):
    open_map(loose)
    find(loose)
    decide(loose, 'reviews.customer_id', 'ignore')
    loose.wait_for_function("!document.querySelector('.tab-content.active .map-suggest-item[data-relation=\"reviews.customer_id\"]')")
    loose.click('.tab-content.active .map-suggest-head .btn')
    find(loose)
    assert 'reviews.customer_id' not in items(loose) and 'Ignored (1)' in loose.inner_text('.tab-content.active .map-suggest-decided')
    assert loose.locator('.tab-content.active .map-edge').count() == 0                 # ignoring draws nothing


def test_an_ignored_suggestion_can_be_asked_for_again(loose):
    open_map(loose)
    find(loose)
    decide(loose, 'reviews.customer_id', 'ignore')
    loose.wait_for_function("!document.querySelector('.tab-content.active .map-suggest-item[data-relation=\"reviews.customer_id\"]')")
    loose.click('.tab-content.active .map-suggest-decided summary')
    loose.click('.tab-content.active .map-suggest-decided [data-act=forget]')
    loose.wait_for_selector('.tab-content.active .map-suggest-item[data-relation="reviews.customer_id"]')


# ---- untrusted text ------------------------------------------------------------------------------------------------------------------

def test_table_and_column_names_stay_plain_text(page, tmp_path):
    path = str(tmp_path / 'hostile.db')
    parent, column = '<img src=x onerror=window.__pwned=1>users', '<img src=x onerror=window.__pwned=1>user_id'
    c = sqlite3.connect(path)
    c.executescript(f'create table "{parent}"(id integer primary key); create table posts(id integer primary key, "{column}" integer);')
    c.executemany(f'insert into "{parent}" values(?)', [(i,) for i in range(1, 11)])
    c.executemany('insert into posts values(?,?)', [(i, i) for i in range(1, 11)])
    c.commit()
    c.close()
    page.click('#manage-connections-btn')
    page.click('#new-connection-btn-manager')
    page.select_option('select[name=type]', 'sqlite')
    page.fill('input[name=name]', 'Hostile')
    page.fill('input[name=database]', path)
    page.click('#connection-form button[type=submit]')
    page.wait_for_selector('.connection-item:has-text("Hostile")')
    connect(page, 'Hostile')
    open_map(page)
    page.click('.tab-content.active [data-map=find-empty]')
    page.wait_for_selector('.tab-content.active .map-suggest-item')
    assert page.locator('.tab-content.active .map-suggest img').count() == 0
    assert parent in page.inner_text('.tab-content.active .map-suggest-title')
    assert page.evaluate('window.__pwned') is None


# ---- the sample shop is the place to try it --------------------------------------------------------------------------------------------

def test_the_sample_shop_walks_through_the_whole_feature(page):
    page.click('#welcome-sample')
    page.wait_for_selector('#tables-content .tree-item', timeout=15000)
    open_map(page)
    # the shop's own keys are drawn; the four add-on tables are left out because nothing declares their links
    assert page.locator('.tab-content.active .map-node').count() == 7
    loose_chips = page.locator('.tab-content.active .map-loose .map-chip').all_inner_texts()
    assert {'support_tickets', 'wishlists', 'coupon_redemptions', 'affiliate_clicks'} <= set(loose_chips)

    find(page)
    got = items(page)
    assert set(got) == {'support_tickets.customer_id', 'support_tickets.order_id', 'wishlists.customer_id', 'wishlists.product_id', 'coupon_redemptions.order_id'}
    assert 'affiliate_clicks.customer_id' not in got                                     # the name fits, the data does not
    assert 'point' in got['coupon_redemptions.order_id']['evidence'] and got['coupon_redemptions.order_id']['confidence'] == 'low'

    decide(page, 'support_tickets.customer_id', 'accept')
    page.wait_for_selector('.tab-content.active .map-edge.is-inferred', state='attached')
    assert page.locator('.tab-content.active .map-node').count() == 8                    # support_tickets joined the map
    assert '1 inferred' in page.inner_text('.tab-content.active .map-info')

    page.locator('.tab-content.active .map-node[data-table="support_tickets"]').click()
    page.wait_for_selector('.tab-content.active td.fk[data-column=customer_id]')
    assert page.locator('.tab-content.active td.fk[data-column=order_id]').count() == 0   # not accepted, so no arrow
    cell = page.locator('.tab-content.active td[data-column=customer_id].fk').first
    box = cell.bounding_box()
    cell.click(position={'x': box['width'] - 10, 'y': box['height'] / 2})
    page.wait_for_function("document.querySelector('#tabs-header .tab.active .tab-label').textContent.startsWith('customers')")
