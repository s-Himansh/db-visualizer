"""Editing through the real UI on the databases that cannot roll back: the key or document is saved, an unchanged one
raises no false alarm, and one someone else changed is reported before it is overwritten."""
import socket

import pytest

from conftest import answer_dialogs, dialogs

pytestmark = pytest.mark.e2e


def up(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def conflicts(page):
    return [d for d in dialogs(page) if 'changed by someone else' in d]


def open_connection(page, name, body, table):
    page.evaluate("""([name, body]) => fetch('/api/connections', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)})""", [name, {'name': name, **body}])
    page.reload()
    page.wait_for_selector('#manage-connections-btn')
    page.click('#manage-connections-btn')
    page.click(f'.connection-item:has-text("{name}") .connect-btn')
    page.wait_for_selector('#tables-content .tree-item', timeout=20000)
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    page.locator('#tables-content .tree-item').filter(has=page.locator(f'.tree-label:text-is("{table}")')).first.click()
    page.wait_for_selector('.tab-content.active .data-table tbody tr')


def edit(page, row, column, text):
    cell = page.locator(f'.tab-content.active tr[data-row-index="{row}"] td[data-column={column}]')
    cell.click()
    page.keyboard.press('ControlOrMeta+A')
    page.keyboard.type(text)
    page.keyboard.press('Tab')
    page.click('.tab-content.active [data-action=save-changes]')


def saved(page):
    page.wait_for_function("document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes('Saved 1 change')")


@pytest.fixture
def redis_key(page):
    if not up(16379):
        pytest.skip('redis test server not running')
    import redis
    r = redis.Redis(port=16379, db=1)
    r.flushdb()
    for i in range(1, 6):
        r.set(f'e2e:{i}', f'value {i}')
    open_connection(page, 'Redis', dict(type='redis', host='127.0.0.1', port=16379, database='1'), 'e2e:*')
    yield r
    r.flushdb()


def test_redis_value_is_saved_from_the_grid_without_a_false_conflict(page, redis_key):
    edit(page, 0, 'value', 'changed in the grid')
    saved(page)
    assert redis_key.get('e2e:1') == b'changed in the grid' and not conflicts(page)


def test_redis_value_changed_elsewhere_is_reported_and_kept(page, redis_key):
    edit_cell = page.locator('.tab-content.active tr[data-row-index="0"] td[data-column=value]')
    edit_cell.click()
    page.keyboard.press('ControlOrMeta+A')
    page.keyboard.type('mine')
    page.keyboard.press('Tab')
    redis_key.set('e2e:1', 'theirs')
    answer_dialogs(page, [True, False])           # accept the review, then "Keep editing"
    page.click('.tab-content.active [data-action=save-changes]')
    page.wait_for_function('window.__dialogs.length >= 2')
    assert 'changed by someone else' in dialogs(page)[-1] and 'theirs' in dialogs(page)[-1]
    assert redis_key.get('e2e:1') == b'theirs'


@pytest.fixture
def mongo_doc(page):
    if not up(27018):
        pytest.skip('mongodb test server not running')
    import pymongo
    coll = pymongo.MongoClient('127.0.0.1', 27018)['dbviz']['e2e_docs']
    coll.drop()
    coll.insert_many([{'id': i, 'name': f'doc {i}'} for i in range(1, 4)])
    open_connection(page, 'Mongo', dict(type='mongodb', host='127.0.0.1', port=27018, database='dbviz'), 'e2e_docs')
    yield coll
    coll.drop()


def test_mongodb_document_is_saved_from_the_grid_without_a_false_conflict(page, mongo_doc):
    edit(page, 0, 'name', 'changed in the grid')
    saved(page)
    assert mongo_doc.find_one({'id': 1})['name'] == 'changed in the grid' and not conflicts(page)
