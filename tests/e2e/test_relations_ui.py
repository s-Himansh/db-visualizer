"""Following foreign keys in the grid, and the schema map. The demo database has:
   customers <- orders <- items,   customers <- reviews,   and a view (paid_orders) that has no relationships."""
import sqlite3

import pytest

from conftest import add_sqlite_connection, connect, dialogs

pytestmark = pytest.mark.e2e


def open_table(pg, name):
    pg.locator('#tables-content .tree-item').filter(has=pg.locator(f'.tree-label:text-is("{name}")')).click()
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


def arrow(pg, selector):
    """Click in the arrow zone at the right edge of a cell."""
    cell = pg.locator(selector).first
    box = cell.bounding_box()
    cell.click(position={'x': box['width'] - 10, 'y': box['height'] / 2})


def active_title(pg):
    return pg.inner_text('#tabs-header .tab.active .tab-label')


def wait_for_tab(pg, prefix):
    """Wait until the tab starting with `prefix` is active and its rows have arrived."""
    pg.wait_for_function(f"document.querySelector('#tabs-header .tab.active .tab-label').textContent.startsWith({prefix!r})")
    pg.wait_for_selector('.tab-content.active .data-table tbody tr')


@pytest.fixture
def linked(connected):
    open_table(connected, 'orders')
    connected.wait_for_selector('.tab-content.active td.fk')   # links are added once the relationships arrive
    return connected


# ---- links in the grid --------------------------------------------------------------------------------

def test_foreign_key_cells_are_marked_and_plain_cells_are_not(linked):
    assert linked.locator('.tab-content.active td[data-column=customer_id].fk').count() == 100
    assert linked.locator('.tab-content.active td[data-column=status].fk').count() == 0
    assert linked.locator('.tab-content.active td[data-column=id].ref').count() == 100   # items point at orders.id


def test_clicking_the_arrow_opens_the_row_it_points_at(linked):
    expected = linked.locator('.tab-content.active tr[data-row-index="0"] td[data-column=customer_id]').get_attribute('data-original-value')
    arrow(linked, '.tab-content.active tr[data-row-index="0"] td[data-column=customer_id]')
    wait_for_tab(linked, 'customers')
    assert active_title(linked) == f'customers · id = {expected}'
    assert linked.locator('.tab-content.active tbody tr').count() == 1
    assert linked.inner_text('.tab-content.active .filter-chip').startswith(f'id = {expected}')


def test_clicking_the_value_itself_still_edits_instead_of_navigating(linked):
    before = linked.locator('#tabs-header .tab').count()
    linked.locator('.tab-content.active tr[data-row-index="0"] td[data-column=customer_id]').first.click(position={'x': 8, 'y': 8})
    linked.wait_for_timeout(500)
    assert linked.locator('#tabs-header .tab').count() == before and active_title(linked) == 'orders'


def test_modifier_click_follows_the_link_from_anywhere_in_the_cell(linked):
    linked.locator('.tab-content.active tr[data-row-index="0"] td[data-column=customer_id]').click(modifiers=['Meta'], position={'x': 8, 'y': 8})
    wait_for_tab(linked, 'customers')


def test_arrow_the_other_way_lists_the_rows_that_point_here(linked):
    arrow(linked, '.tab-content.active tr[data-row-index="0"] td[data-column=id]')   # order 1 is referenced by 2 items
    wait_for_tab(linked, 'items')
    assert active_title(linked) == 'items · order_id = 1'
    assert linked.locator('.tab-content.active tbody tr').count() == 2


def test_a_value_pointed_at_by_several_tables_asks_which(connected):
    open_table(connected, 'customers')
    connected.wait_for_selector('.tab-content.active td.ref')
    arrow(connected, '.tab-content.active tr[data-row-index="1"] td[data-column=id]')   # customer 2: orders and reviews
    connected.wait_for_selector('.table-context-menu')
    entries = connected.locator('.table-context-menu .context-menu-item').all_inner_texts()
    assert sorted(entries) == ['orders.customer_id', 'reviews.customer_id']
    connected.click('.table-context-menu >> text="reviews.customer_id"')
    wait_for_tab(connected, 'reviews')
    assert connected.locator('.tab-content.active tbody tr').count() == 2


def test_null_values_are_not_links(connected):
    open_table(connected, 'items')
    connected.wait_for_selector('.tab-content.active td.fk')
    assert connected.locator('.tab-content.active td[data-column=order_id].fk').count() == 4   # 5 rows, one NULL


def test_following_the_same_link_twice_reuses_the_tab(linked):
    for _ in range(2):
        arrow(linked, '.tab-content.active tr[data-row-index="0"] td[data-column=customer_id]')
        wait_for_tab(linked, 'customers')
        linked.click('#tabs-header .tab:has-text("orders"):not(:has-text("·"))')
    assert linked.locator('#tabs-header .tab:has-text("customers ·")').count() == 1


def test_the_filter_chip_clears_the_filter(linked):
    arrow(linked, '.tab-content.active tr[data-row-index="0"] td[data-column=customer_id]')
    linked.wait_for_selector('.tab-content.active .filter-chip', state='visible')
    linked.click('.tab-content.active .filter-chip button')
    linked.wait_for_function("document.querySelectorAll('.tab-content.active .data-table tbody tr').length === 30")
    assert not linked.is_visible('.tab-content.active .filter-chip')
    assert active_title(linked) == 'customers'


def test_filtered_view_matches_the_database(linked):
    arrow(linked, '.tab-content.active tr[data-row-index="0"] td[data-column=id]')
    wait_for_tab(linked, 'items')
    c = sqlite3.connect(linked.demo_db)
    expected = c.execute('select count(*) from items where order_id = 1').fetchone()[0]
    c.close()
    assert linked.locator('.tab-content.active tbody tr').count() == expected == 2


def test_removing_the_filter_with_unsaved_changes_asks_first(linked):
    arrow(linked, '.tab-content.active tr[data-row-index="0"] td[data-column=id]')
    linked.wait_for_selector('.tab-content.active .filter-chip', state='visible')
    linked.click('.tab-content.active [data-action=add-row]')
    linked.evaluate("window.__dialogAnswer = false")
    linked.click('.tab-content.active .filter-chip button')
    linked.wait_for_timeout(400)
    assert any('unsaved' in d for d in dialogs(linked))
    assert linked.is_visible('.tab-content.active .filter-chip')


# ---- the schema map ---------------------------------------------------------------------------------------

def node(pg, name):
    return pg.locator(f'.tab-content.active .map-node[data-table="{name}"]')


@pytest.fixture
def map_open(connected):
    connected.click('#open-map-btn')
    connected.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    return connected


def test_map_button_is_disabled_until_a_database_is_open(page):
    assert page.is_disabled('#open-map-btn')


def test_map_draws_every_related_table_and_relationship(map_open):
    names = map_open.locator('.tab-content.active .map-node').evaluate_all("els => els.map(e => e.dataset.table).sort()")
    assert names == ['customers', 'items', 'orders', 'reviews']
    assert map_open.locator('.tab-content.active .map-edge').count() == 3
    assert '5 tables' in map_open.inner_text('.tab-content.active .map-info') and '3 relationships' in map_open.inner_text('.tab-content.active .map-info')


def test_parents_sit_left_of_their_children(map_open):
    x = {n: node(map_open, n).bounding_box()['x'] for n in ('customers', 'orders', 'items', 'reviews')}
    assert x['customers'] < x['orders'] < x['items']
    assert abs(x['reviews'] - x['orders']) < 4   # both are direct children of customers


def test_tables_without_relationships_are_listed_below(map_open):
    assert map_open.locator('.tab-content.active .map-chip').all_inner_texts() == ['paid_orders']


def test_each_node_shows_the_columns_that_link_it(map_open):
    text = node(map_open, 'orders').text_content()
    assert 'customer_id' in text and 'id' in text and 'FK' in text and 'ref' in text


def test_hovering_a_table_highlights_only_what_it_touches(map_open):
    node(map_open, 'orders').hover()
    assert map_open.evaluate("document.querySelector('.tab-content.active .map-svg').classList.contains('has-focus')")
    on = map_open.locator('.tab-content.active .map-node.on').evaluate_all("els => els.map(e => e.dataset.table).sort()")
    assert on == ['customers', 'items', 'orders']          # reviews is not connected to orders
    assert map_open.locator('.tab-content.active .map-edge.on').count() == 2


def test_clicking_a_table_opens_its_data(map_open):
    node(map_open, 'orders').click()
    map_open.wait_for_selector('.tab-content.active .data-table tbody tr')
    assert active_title(map_open) == 'orders'


def test_search_marks_matches_and_dims_the_rest(map_open):
    map_open.fill('.tab-content.active .map-search', 'ite')
    assert 'match' in node(map_open, 'items').get_attribute('class')
    assert 'faded' in node(map_open, 'orders').get_attribute('class')
    map_open.fill('.tab-content.active .map-search', '')
    assert map_open.locator('.tab-content.active .map-node.faded, .tab-content.active .map-node.match').count() == 0


def test_everything_is_in_view_after_fit_and_zoom_changes_the_scale(map_open):
    canvas = map_open.locator('.tab-content.active .map-canvas').bounding_box()
    for name in ('customers', 'orders', 'items', 'reviews'):
        b = node(map_open, name).bounding_box()
        assert canvas['x'] <= b['x'] and b['x'] + b['width'] <= canvas['x'] + canvas['width'] + 1
        assert canvas['y'] <= b['y'] and b['y'] + b['height'] <= canvas['y'] + canvas['height'] + 1
    before = node(map_open, 'orders').bounding_box()['width']
    map_open.click('.tab-content.active [data-map=zoom-in]')
    assert node(map_open, 'orders').bounding_box()['width'] > before


def test_dragging_pans_without_opening_a_table(map_open):
    before = node(map_open, 'customers').bounding_box()
    tabs = map_open.locator('#tabs-header .tab').count()
    box = map_open.locator('.tab-content.active .map-canvas').bounding_box()
    map_open.mouse.move(box['x'] + 30, box['y'] + 30)
    map_open.mouse.down()
    map_open.mouse.move(box['x'] + 130, box['y'] + 90, steps=5)
    map_open.mouse.up()
    after = node(map_open, 'customers').bounding_box()
    assert round(after['x'] - before['x']) == 100 and round(after['y'] - before['y']) == 60
    assert map_open.locator('#tabs-header .tab').count() == tabs


def test_opening_the_map_twice_reuses_the_tab(map_open):
    map_open.click('#open-map-btn')
    assert map_open.locator('#tabs-header .tab:has-text("Schema map")').count() == 1


def test_a_database_without_foreign_keys_explains_itself(page, tmp_path):
    plain = tmp_path / 'plain.db'
    c = sqlite3.connect(plain)
    c.execute('create table a(id integer primary key)')
    c.execute('create table b(id integer primary key)')
    c.commit()
    c.close()
    page.demo_db = str(plain)
    add_sqlite_connection(page, name='Plain')
    connect(page, name='Plain')
    page.click('#open-map-btn')
    page.wait_for_selector('.tab-content.active .map-empty')
    assert 'No foreign keys' in page.inner_text('.tab-content.active .map-empty')
    assert sorted(page.locator('.tab-content.active .map-chip').all_inner_texts()) == ['a', 'b']


def test_refreshing_the_map_does_not_stack_up_pan_handlers(map_open):
    for _ in range(3):
        map_open.click('.tab-content.active [data-map=refresh]')
        map_open.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    before = node(map_open, 'customers').bounding_box()
    box = map_open.locator('.tab-content.active .map-canvas').bounding_box()
    map_open.mouse.move(box['x'] + 30, box['y'] + 30)
    map_open.mouse.down()
    map_open.mouse.move(box['x'] + 130, box['y'] + 30, steps=5)
    map_open.mouse.up()
    assert round(node(map_open, 'customers').bounding_box()['x'] - before['x']) == 100   # moved once, not four times


# ---- edges never pass through tables --------------------------------------------------------------------------

CROSSING_CHECK = """() => {
    const svg = document.querySelector('.tab-content.active .map-svg');
    const boxes = [...svg.querySelectorAll('.map-node')].map(g => {
        const m = /translate\\(([-\\d.]+),([-\\d.]+)\\)/.exec(g.getAttribute('transform'));
        const b = g.querySelector('.map-node-box');
        const x = +m[1], y = +m[2], w = +b.getAttribute('width'), h = +b.getAttribute('height');
        return { name: g.dataset.table, x: x + 1.5, y: y + 1.5, r: x + w - 1.5, b: y + h - 1.5 };
    });
    const hits = [];
    svg.querySelectorAll('.map-edge').forEach(p => {
        const len = p.getTotalLength();
        for (let l = 0; l <= len; l += 3) {
            const pt = p.getPointAtLength(l);
            for (const n of boxes) if (pt.x > n.x && pt.x < n.r && pt.y > n.y && pt.y < n.b) hits.push(p.querySelector('title').textContent + ' through ' + n.name);
        }
    });
    return [...new Set(hits)];
}"""


def test_no_edge_passes_through_a_table_on_the_sample_shop(page):
    page.click('#welcome-sample')
    page.wait_for_selector('#tables-content .tree-item', timeout=15000)
    page.click('#open-map-btn')
    page.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    assert page.evaluate(CROSSING_CHECK) == []


@pytest.fixture
def tangled(page, tmp_path):
    path = tmp_path / 'tangled.db'
    c = sqlite3.connect(path)
    c.executescript('''
        create table a(id integer primary key);
        create table b(id integer primary key, a_id integer references a(id));
        create table c(id integer primary key, b_id integer references b(id), a_id integer references a(id));
        create table d(id integer primary key, c_id integer references c(id), a_id integer references a(id), b_id integer references b(id));
        create table e(id integer primary key, d_id integer references d(id), a_id integer references a(id), c_id integer references c(id));
        create table f(id integer primary key, e_id integer references e(id), c_id integer references c(id), a_id integer references a(id));
        create table g(id integer primary key, f_id integer references f(id), a_id integer references a(id), b_id integer references b(id), d_id integer references d(id));
        create table x(id integer primary key, y_id integer);
        create table y(id integer primary key, x_id integer references x(id));
        create table z(id integer primary key, a_id integer references a(id), g_id integer references g(id), self_id integer references z(id));
    ''')
    c.commit()
    c.close()
    page.demo_db = str(path)
    add_sqlite_connection(page, name='Tangled')
    connect(page, name='Tangled')
    page.click('#open-map-btn')
    page.wait_for_selector('.tab-content.active .map-svg[data-ready]')
    return page


def test_no_edge_passes_through_a_table_in_a_tangled_schema(tangled):
    assert tangled.locator('.tab-content.active .map-node').count() == 10
    assert tangled.locator('.tab-content.active .map-edge').count() == 20
    assert tangled.evaluate(CROSSING_CHECK) == []


def test_parallel_long_edges_get_their_own_lanes(tangled):
    ys = tangled.evaluate("""() => [...document.querySelectorAll('.tab-content.active .map-edge')]
        .map(p => p.getAttribute('d'))
        .filter(d => d.includes('Q'))                       // routed (long) edges have rounded corners
        .map(d => { const m = d.match(/L[-\\d.]+,([-\\d.]+) Q/g); return m && m[1] ? m[1] : d; })""")
    assert len(ys) >= 6 and len(set(ys)) == len(ys)


def test_everything_including_the_lanes_is_in_view_after_fit(tangled):
    canvas = tangled.locator('.tab-content.active .map-canvas').bounding_box()
    box = tangled.locator('.tab-content.active .map-viewport').bounding_box()
    assert canvas['x'] - 1 <= box['x'] and box['x'] + box['width'] <= canvas['x'] + canvas['width'] + 1
    assert canvas['y'] - 1 <= box['y'] and box['y'] + box['height'] <= canvas['y'] + canvas['height'] + 1


# ---- grid layout -------------------------------------------------------------------------------------------------

def test_a_link_arrow_sits_next_to_its_value_not_across_the_screen(linked):
    cell = linked.locator('.tab-content.active tr[data-row-index="0"] td[data-column=id]').bounding_box()
    assert cell['width'] < 110           # a column holding a number is as wide as that number needs, not 150px


def test_long_text_still_gets_room_and_short_columns_stay_narrow(connected):
    open_table(connected, 'customers')
    widths = connected.evaluate("""() => Object.fromEntries([...document.querySelectorAll('.tab-content.active thead th[data-col]')]
        .map(th => [th.dataset.col, th.getBoundingClientRect().width]))""")
    assert widths['id'] < 110 and widths['email'] > 1.4 * widths['id']
