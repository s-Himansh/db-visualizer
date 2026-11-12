"""The record explorer: right-click a row, see the rows linked to it, step through them.
Demo data: customer 2 has 9 orders and 2 reviews; order 1 belongs to customer 2 and has 2 items; item 4 belongs to no order."""
import pytest

from conftest import connect
from test_relations_ui import open_table

pytestmark = pytest.mark.e2e


def explore(pg, row_index):
    pg.locator('.tab-content.active .data-table tbody tr').nth(row_index).locator('td').nth(1).click(button='right')
    pg.click('.table-context-menu .context-menu-item:text-is("Explore this record")')
    pg.wait_for_selector('#explorer-modal.active')


def group_names(pg):
    return pg.locator('#explorer-body .explore-group-name').all_inner_texts()


def test_a_customer_shows_its_orders_and_reviews(connected):
    open_table(connected, 'customers')
    connected.wait_for_selector('.tab-content.active td.ref')
    explore(connected, 1)                                      # customer 2
    connected.wait_for_selector('#explorer-body .explore-group')
    assert connected.inner_text('#explorer-title').startswith('customers:')
    assert sorted(group_names(connected)) == ['orders', 'reviews']
    orders = connected.locator('#explorer-body .explore-group').filter(has_text='orders')
    assert orders.locator('.explore-group-count').inner_text() == '9'
    assert orders.locator('.explore-row').count() == 5          # the first few, not all nine
    assert 'Show all 9 in the grid' in orders.inner_text()


def test_stepping_into_a_row_and_back(connected):
    open_table(connected, 'customers')
    connected.wait_for_selector('.tab-content.active td.ref')
    explore(connected, 1)
    connected.wait_for_selector('#explorer-body .explore-group')
    connected.locator('#explorer-body .explore-group').filter(has_text='orders').locator('.explore-row').first.click()
    connected.wait_for_function("document.querySelector('#explorer-title').textContent.startsWith('orders:')")
    connected.wait_for_selector('#explorer-body .explore-heading:text-is("Referenced by")')
    assert sorted(group_names(connected)) == ['customers', 'items']
    connected.click('#explorer-back')
    connected.wait_for_function("document.querySelector('#explorer-title').textContent.startsWith('customers:')")
    assert connected.is_hidden('#explorer-back')


def test_show_all_opens_exactly_those_rows_in_the_grid(connected):
    open_table(connected, 'customers')
    connected.wait_for_selector('.tab-content.active td.ref')
    explore(connected, 1)
    connected.wait_for_selector('#explorer-body .explore-group')
    connected.click('#explorer-body .explore-all')
    connected.wait_for_selector('#explorer-modal.active', state='hidden')
    connected.wait_for_function("document.querySelector('#tabs-header .tab.active .tab-label').textContent.startsWith('orders')")
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')
    assert connected.locator('.tab-content.active .data-table tbody tr').count() == 9


def test_a_row_with_no_linked_values_says_so(connected):
    open_table(connected, 'items')
    connected.wait_for_selector('.tab-content.active td.fk')
    explore(connected, 3)                                      # item 4 has no order
    connected.wait_for_selector('#explorer-body .form-hint')
    assert 'no linked values' in connected.inner_text('#explorer-body')


def test_row_values_are_shown_as_plain_text(connected):
    open_table(connected, 'customers')
    connected.wait_for_selector('.tab-content.active td.ref')
    explore(connected, 6)                                      # customer 7 is named  O'Brien <b>
    connected.wait_for_function("document.querySelector('#explorer-title').textContent.includes('<b>')")
    assert connected.locator('#explorer-title b').count() == 0
