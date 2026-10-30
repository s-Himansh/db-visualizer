import hashlib
import sqlite3

import pytest

import db
from sample_data import build_sample


@pytest.fixture
def sample_db(tmp_path):
    return build_sample(tmp_path / 'shop.db')


def rows(path, sql):
    c = sqlite3.connect(path)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def test_every_foreign_key_in_the_sample_is_valid(sample_db):
    assert rows(sample_db, 'PRAGMA foreign_key_check') == []


def test_the_sample_has_a_realistic_amount_of_connected_data(sample_db):
    counts = dict(rows(sample_db, """
        SELECT 'categories', COUNT(*) FROM categories UNION ALL SELECT 'products', COUNT(*) FROM products
        UNION ALL SELECT 'customers', COUNT(*) FROM customers UNION ALL SELECT 'orders', COUNT(*) FROM orders
        UNION ALL SELECT 'order_items', COUNT(*) FROM order_items UNION ALL SELECT 'shipments', COUNT(*) FROM shipments
        UNION ALL SELECT 'reviews', COUNT(*) FROM reviews"""))
    assert counts['customers'] == 120 and counts['orders'] == 420 and counts['products'] == 30
    assert all(n > 0 for n in counts.values()) and counts['order_items'] > counts['orders']


def test_order_totals_really_are_the_sum_of_their_items(sample_db):
    assert rows(sample_db, """
        SELECT COUNT(*) FROM orders o
        WHERE ABS(o.total - (SELECT SUM(quantity * unit_price) FROM order_items WHERE order_id = o.id)) > 0.01""") == [(0,)]


def test_it_includes_a_self_reference_nulls_json_and_a_view(sample_db):
    assert rows(sample_db, 'SELECT COUNT(*) FROM customers WHERE referred_by IS NOT NULL')[0][0] > 0
    assert rows(sample_db, 'SELECT COUNT(*) FROM customers WHERE referred_by IS NULL')[0][0] > 0
    assert rows(sample_db, 'SELECT COUNT(*) FROM customers WHERE preferences LIKE \'{%\'')[0][0] > 0
    assert rows(sample_db, "SELECT COUNT(*) FROM sqlite_master WHERE type = 'view' AND name = 'revenue_by_country'") == [(1,)]
    assert rows(sample_db, 'SELECT COUNT(*) FROM revenue_by_country')[0][0] > 0


def test_it_is_deterministic(tmp_path):
    def digest(p):
        c = sqlite3.connect(p)
        out = hashlib.sha256('\n'.join(c.iterdump()).encode()).hexdigest()
        c.close()
        return out
    assert digest(build_sample(tmp_path / 'a.db')) == digest(build_sample(tmp_path / 'b.db'))


def test_a_failed_build_never_leaves_a_half_written_file(tmp_path, monkeypatch):
    monkeypatch.setattr('sample_data.SCHEMA', 'THIS IS NOT SQL')
    with pytest.raises(sqlite3.Error):
        build_sample(tmp_path / 'shop.db')
    assert not (tmp_path / 'shop.db').exists()


# ---- the API ---------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_sample_file():
    sample = db.CONFIG_DIR / 'sample' / 'shop.db'
    sample.unlink(missing_ok=True)
    yield


def test_sample_endpoint_creates_one_connection_however_often_it_is_called(client):
    ids = {client.post('/api/sample').get_json()['id'] for _ in range(3)}
    assert len(ids) == 1
    saved = [c for c in client.get('/api/connections').get_json()['connections'] if c.get('sample')]
    assert len(saved) == 1 and saved[0]['name'] == 'Sample shop' and saved[0]['environment'] == 'local'


def test_the_sample_connects_and_has_the_expected_relationships(client):
    cid = client.post('/api/sample').get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']
    rel = client.get(f'/api/relations?connection_id={cid}').get_json()
    assert len(rel['relations']) == 9
    assert {t['name'] for t in rel['tables']} >= {'orders', 'customers', 'order_items', 'revenue_by_country'}


def test_a_deleted_sample_file_is_rebuilt(client):
    cid = client.post('/api/sample').get_json()['id']
    (db.CONFIG_DIR / 'sample' / 'shop.db').unlink()
    assert client.post('/api/sample').get_json()['id'] == cid
    assert (db.CONFIG_DIR / 'sample' / 'shop.db').exists()


def test_connection_ids_do_not_collide_with_the_samples(client):
    sample = client.post('/api/sample').get_json()['id']
    other = client.post('/api/connections', json={'name': 'x', 'type': 'mysql'}).get_json()['id']
    assert sample != other


# ---- environments -----------------------------------------------------------------------------------------

@pytest.mark.parametrize('env', ['', 'local', 'development', 'staging', 'production'])
def test_known_environments_are_saved(client, env):
    cid = client.post('/api/connections', json={'name': 'x', 'type': 'mysql', 'environment': env}).get_json()['id']
    saved = next(c for c in client.get('/api/connections').get_json()['connections'] if c['id'] == cid)
    assert saved.get('environment', '') == env


def test_unknown_environments_are_rejected_on_create_and_update(client):
    assert client.post('/api/connections', json={'name': 'x', 'type': 'mysql', 'environment': 'prod!'}).status_code == 400
    cid = client.post('/api/connections', json={'name': 'x', 'type': 'mysql'}).get_json()['id']
    assert client.put(f'/api/connections/{cid}', json={'environment': '<script>'}).status_code == 400
