"""64-bit ids (snowflakes and the like) are bigger than a browser's numbers can hold. They must show exactly as stored,
and editing the row next to one must change that row, not fail to find it."""
import sqlite3

import pytest

from conftest import add_sqlite_connection, connect

pytestmark = pytest.mark.e2e

IDS = [1234567890123456789, 9007199254740993, -9007199254740993]


@pytest.fixture
def big(page):
    s = sqlite3.connect(page.demo_db)
    s.execute('create table events(id integer primary key, name text, ref integer)')
    s.executemany('insert into events values(?, ?, ?)', [(i, f'event {n}', i) for n, i in enumerate(IDS)])
    s.commit()
    s.close()
    add_sqlite_connection(page)
    connect(page)
    page.locator('#tables-content .tree-item').filter(has=page.locator('.tree-label:text-is("events")')).click()
    page.wait_for_selector('.tab-content.active .data-table tbody tr')
    return page


def test_large_numbers_are_shown_exactly(big):
    shown = big.locator('.tab-content.active tbody td[data-column=id]').all_inner_texts()
    assert sorted(t.strip() for t in shown) == sorted(str(i) for i in IDS)


def test_editing_next_to_a_large_id_changes_that_row(big):
    cell = big.locator('.tab-content.active tbody tr:has(td[data-column=id]:text-is("1234567890123456789")) td[data-column=name]')
    cell.click()
    big.keyboard.press('ControlOrMeta+A')
    big.keyboard.type('edited')
    big.keyboard.press('Tab')
    big.click('.tab-content.active [data-action=save-changes]')
    big.wait_for_function("document.querySelector('#toast-stack') && /Saved 1 change|Nothing was saved|failed/.test(document.querySelector('#toast-stack').innerText)")
    assert 'Saved 1 change' in big.inner_text('#toast-stack'), big.inner_text('#toast-stack')
    s = sqlite3.connect(big.demo_db)
    try:
        assert s.execute('select name from events where id = 1234567890123456789').fetchone() == ('edited',)
    finally:
        s.close()
