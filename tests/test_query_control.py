"""Row cap, timeout, cancel and reconnect, driven through the HTTP API."""
import threading
import time

import pytest

import db

ENDLESS = 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c'


def connect(client, path):
    cid = client.post('/api/connections', json={'name': 'x', 'type': 'sqlite', 'database': path}).get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']
    return cid


def query(client, cid, sql, **extra):
    return client.post('/api/query', json={'connection_id': cid, 'query': sql, **extra})


def test_result_is_capped_and_flagged(client, sqlite_path):
    cid = connect(client, sqlite_path)
    sql = 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 10500) SELECT x FROM c'
    r = query(client, cid, sql).get_json()['result']
    assert len(r['rows']) == 10_000 and r['row_count'] == 10_000 and r['truncated'] is True


def test_result_under_the_cap_is_not_flagged(client, sqlite_path):
    cid = connect(client, sqlite_path)
    r = query(client, cid, 'select * from t').get_json()['result']
    assert r['row_count'] == 3 and not r.get('truncated')


def test_driver_never_pulls_more_than_cap_plus_one(sqlite_path):
    from db_connectors.sqlite import SQLiteConnector
    c = SQLiteConnector({'type': 'sqlite', 'database': sqlite_path})
    c.connect()
    r = c.execute_query('WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 50000) SELECT x FROM c')
    assert len(r['rows']) == c.MAX_ROWS + 1  # enough to know it was truncated, not the whole 50,000


def test_runaway_query_is_stopped_by_the_time_limit(client, sqlite_path, monkeypatch):
    monkeypatch.setattr(db, 'QUERY_TIMEOUT', 1)
    cid = connect(client, sqlite_path)
    start = time.time()
    body = query(client, cid, ENDLESS).get_json()
    assert time.time() - start < 5
    assert body['success'] is False and 'longer than 1 seconds' in body['error']
    assert query(client, cid, 'select 1').get_json()['success']  # the connection survived


def test_cancel_stops_a_running_query_and_connection_stays_usable(client, sqlite_path):
    cid = connect(client, sqlite_path)
    out = {}

    def run():
        c = db.app.test_client()
        c.environ_base['HTTP_X_DBV_TOKEN'] = db.APP_TOKEN
        out['body'] = query(c, cid, ENDLESS).get_json()

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.4)
    assert client.post('/api/query/cancel', json={'connection_id': cid}).get_json()['success']
    t.join(5)
    assert not t.is_alive()
    assert out['body']['success'] is False and out['body']['error'] == 'Query cancelled.'
    assert query(client, cid, 'select 1').get_json()['success']


def test_cancel_on_unknown_connection(client):
    assert client.post('/api/query/cancel', json={'connection_id': 'nope'}).status_code == 400


def test_cancel_reports_when_the_database_cannot_do_it(client, monkeypatch):
    class NoCancel:
        db_type = 'fake'
        connection_params = {}
        def __init__(self, p): pass
        def connect(self): return True
        def cancel(self): return False
    monkeypatch.setitem(db.CONNECTOR_CLASSES, 'fake', NoCancel)
    cid = client.post('/api/connections', json={'name': 'f', 'type': 'fake'}).get_json()['id']
    client.post('/api/connect', json={'id': cid})
    r = client.post('/api/query/cancel', json={'connection_id': cid}).get_json()
    assert r['success'] is False and 'cannot stop' in r['error']


# ---- reconnect ---------------------------------------------------------------------

def test_dead_connection_is_reopened_after_idling(client, sqlite_path):
    cid = connect(client, sqlite_path)
    wrapper = db.active_connections[cid]
    wrapper._connector.connection.close()   # what a server-side drop looks like to the app
    wrapper._last_used -= 120               # ...discovered after a lunch break
    r = client.get(f'/api/tables?connection_id={cid}')
    assert r.status_code == 200 and [t['name'] for t in r.get_json()['tables']] == ['t']


def test_dead_connection_is_reopened_after_a_failed_call(client, sqlite_path):
    cid = connect(client, sqlite_path)
    db.active_connections[cid]._connector.connection.close()
    first = query(client, cid, 'select 1').get_json()          # fails: the drop was not known yet
    assert first['success'] is False
    assert query(client, cid, 'select 1').get_json()['success']  # the failure made the next call check and reconnect


def test_healthy_idle_connection_is_not_reopened(client, sqlite_path):
    cid = connect(client, sqlite_path)
    wrapper = db.active_connections[cid]
    before = wrapper._connector.connection
    wrapper._last_used -= 120
    client.get(f'/api/tables?connection_id={cid}')
    assert wrapper._connector.connection is before


def test_unrecoverable_connection_returns_503_with_a_clear_message(client, monkeypatch):
    class Dying:
        db_type = 'fake'
        connection_params = {}
        alive = True
        def __init__(self, p): pass
        def connect(self): return Dying.alive
        def disconnect(self): return True
        def ping(self): return False
        def get_tables(self, database=None): return []
    monkeypatch.setitem(db.CONNECTOR_CLASSES, 'fake', Dying)
    cid = client.post('/api/connections', json={'name': 'f', 'type': 'fake'}).get_json()['id']
    client.post('/api/connect', json={'id': cid})
    Dying.alive = False
    db.active_connections[cid]._last_used -= 120
    r = client.get(f'/api/tables?connection_id={cid}')
    assert r.status_code == 503 and 'could not be re-opened' in r.get_json()['error']
