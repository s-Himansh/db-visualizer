import pytest
import base64
import json
from pathlib import Path

import db


def get_data(client, cid, path, **params):
    return client.get('/api/data', query_string=dict(connection_id=cid, table='t', database=path, **params))


# --- local API protection -------------------------------------------------

def test_api_requires_token():
    assert db.app.test_client().get('/api/connections').status_code == 403


def test_rejects_foreign_host(client):
    assert client.get('/api/connections', headers={'Host': 'evil.example.com'}).status_code == 403


def test_index_carries_token_and_no_cdn(client):
    html = client.get('/').get_data(as_text=True)
    assert db.APP_TOKEN in html
    assert 'cdnjs' not in html and 'https://' not in html.replace('http://www.w3.org', '')


def test_no_cors_headers(client):
    r = client.get('/api/connections', headers={'Origin': 'https://evil.example.com'})
    assert 'Access-Control-Allow-Origin' not in r.headers


# --- connections ------------------------------------------------------------

def test_password_masked_encrypted_and_kept_on_edit(client):
    cid = client.post('/api/connections', json={'name': 'p', 'type': 'mysql', 'password': 'hunter2'}).get_json()['id']
    assert client.get('/api/connections').get_json()['connections'][0]['password'] == '***'
    assert 'hunter2' not in db.CONNECTIONS_FILE.read_text()
    for blank in ('', '***'):
        assert client.put(f'/api/connections/{cid}', json={'name': 'renamed', 'password': blank}).get_json()['success']
        assert db.load_connections()[0]['password'] == 'hunter2'
    assert db.load_connections()[0]['name'] == 'renamed'


def test_corrupt_file_is_backed_up_not_overwritten(client):
    db.CONNECTIONS_FILE.write_text('{not json')
    assert client.get('/api/connections').get_json()['connections'] == []
    assert db.CONNECTIONS_FILE.with_suffix('.corrupt').read_text() == '{not json'


def test_undecryptable_password_keeps_connection(client):
    client.post('/api/connections', json={'name': 'p', 'type': 'mysql', 'password': 'x'})
    data = json.loads(db.CONNECTIONS_FILE.read_text())
    data[0]['password'] = 'garbage'
    db.CONNECTIONS_FILE.write_text(json.dumps(data))
    assert len(db.load_connections()) == 1


def test_secret_files_are_private():
    client_pw = db.encrypt_password('x')  # creates the key if missing
    assert client_pw
    assert oct(db.KEY_FILE.stat().st_mode & 0o777) == '0o600'


def test_cert_upload_becomes_file_and_is_removed_on_delete(client):
    cert = base64.b64encode(b'CERT').decode()
    cid = client.post('/api/connections', json={
        'name': 'c', 'type': 'postgresql', 'use_ssl': True, 'ca_cert': cert, 'ca_cert_filename': 'ca.pem'}).get_json()['id']
    saved = db.load_connections()[0]
    assert 'ca_cert' not in saved and Path(saved['ca_cert_path']).read_bytes() == b'CERT'
    client.delete(f'/api/connections/{cid}')
    assert not (db.CERTS_DIR / cid).exists()


def test_unsupported_type(client):
    assert client.post('/api/test-connection', json={'type': 'nope'}).status_code == 400


# --- data access -------------------------------------------------------------

def test_paging_sort_and_total(client, conn_id, sqlite_path):
    d = get_data(client, conn_id, sqlite_path, limit=2, sort_by='name', sort_order='desc').get_json()['data']
    assert d['total_count'] == 3 and [r['name'] for r in d['rows']] == ['beta', 'alpha'] and d['has_more']


def test_search_all_columns_specific_column_and_quotes(client, conn_id, sqlite_path):
    def n(**kw):
        return get_data(client, conn_id, sqlite_path, **kw).get_json()['data']['total_count']
    assert n(search='ALP') == 1
    assert n(search='2') == 1                      # numeric column matched
    assert n(search='a', search_column='name') == 2
    assert n(search="O'B") == 1                    # quote-safe
    assert n(search='zzz') == 0


def test_sort_injection_rejected(client, conn_id, sqlite_path):
    assert get_data(client, conn_id, sqlite_path, sort_by='name;drop table t').status_code == 400
    assert get_data(client, conn_id, sqlite_path, search='a', search_column='x" OR 1=1 --').status_code == 400
    assert get_data(client, conn_id, sqlite_path, sort_order='ASC;drop table t').status_code == 200
    assert get_data(client, conn_id, sqlite_path).get_json()['data']['total_count'] == 3


def test_bad_paging_params(client, conn_id, sqlite_path):
    assert get_data(client, conn_id, sqlite_path, limit='abc').status_code == 400
    assert len(get_data(client, conn_id, sqlite_path, limit=-5).get_json()['data']['rows']) == 1  # clamped to >= 1


def test_database_errors_surface(client, conn_id, sqlite_path):
    r = client.get('/api/data', query_string=dict(connection_id=conn_id, table='missing', database=sqlite_path))
    assert r.status_code == 500 and 'missing' in r.get_json()['error']


def test_insert_update_delete_roundtrip(client, conn_id, sqlite_path):
    base = dict(connection_id=conn_id, table='t')
    assert client.post('/api/data', json={**base, 'data': {'name': 'd', 'v': 4}}).get_json()['success']
    assert client.put('/api/data', json={**base, 'conditions': {'name': 'd'}, 'data': {'v': 5}}).get_json()['success']
    assert client.delete('/api/data', json={**base, 'conditions': {'name': 'd'}}).get_json()['success']
    assert get_data(client, conn_id, sqlite_path).get_json()['data']['total_count'] == 3


def test_malformed_body_is_400_not_500(client):
    r = client.post('/api/query', data='not json', content_type='application/json')
    assert r.status_code == 400


def test_not_connected(client):
    assert client.get('/api/tables?connection_id=nope').status_code == 400


# --- one shared DB connection, many parallel UI requests -----------------------

def test_requests_to_one_connection_are_serialized(client, monkeypatch):
    """The UI fires ~10 schema requests at once on connect. Most drivers (pymysql, sqlite) cannot share
    one connection across threads: concurrent use gave 'Command Out of Sync' / '(0, "")' on MySQL."""
    import concurrent.futures as cf
    import threading
    import time

    state = {'inside': 0, 'max': 0}
    lock = threading.Lock()

    class Fake:
        db_type = 'fake'
        connection_params = {'database': 'd'}

        def __init__(self, params): pass
        def connect(self): return True
        def is_connected(self): return True

        def get_schema(self, table, database=None):
            with lock:
                state['inside'] += 1
                state['max'] = max(state['max'], state['inside'])
            time.sleep(0.02)
            with lock:
                state['inside'] -= 1
            return {'columns': []}

    monkeypatch.setitem(db.CONNECTOR_CLASSES, 'fake', Fake)
    cid = client.post('/api/connections', json={'name': 'f', 'type': 'fake'}).get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']

    def call(i):
        c = db.app.test_client()
        c.environ_base['HTTP_X_DBV_TOKEN'] = db.APP_TOKEN
        return c.get(f'/api/schema?connection_id={cid}&table=t{i}').status_code

    with cf.ThreadPoolExecutor(10) as ex:
        codes = list(ex.map(call, range(20)))
    assert set(codes) == {200}
    assert state['max'] == 1


# --- read-only connections and destructive-statement confirmation -----------------

def _sqlite_conn(client, path, **extra):
    cid = client.post('/api/connections', json={'name': 'x', 'type': 'sqlite', 'database': path, **extra}).get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']
    return cid


def _rows(path):
    import sqlite3
    c = sqlite3.connect(path)
    try:
        return c.execute('select count(*) from t').fetchone()[0]
    finally:
        c.close()


def test_read_only_connection_blocks_writes_everywhere(client, sqlite_path):
    cid = _sqlite_conn(client, sqlite_path, read_only=True)
    q = lambda sql: client.post('/api/query', json={'connection_id': cid, 'query': sql})
    assert q('select * from t').get_json()['success']
    for sql in ('delete from t where id = 1', 'insert into t(name) values (\'x\')', 'drop table t',
                'select 1; delete from t where id = 1'):
        r = q(sql)
        assert r.status_code == 403 and r.get_json()['read_only'], sql
    base = {'connection_id': cid, 'table': 't'}
    assert client.post('/api/data', json={**base, 'data': {'name': 'x'}}).status_code == 403
    assert client.put('/api/data', json={**base, 'conditions': {'id': 1}, 'data': {'name': 'x'}}).status_code == 403
    assert client.delete('/api/data', json={**base, 'conditions': {'id': 1}}).status_code == 403
    assert _rows(sqlite_path) == 3  # nothing changed


def test_read_only_still_allows_browsing(client, sqlite_path):
    cid = _sqlite_conn(client, sqlite_path, read_only=True)
    assert get_data(client, cid, sqlite_path).get_json()['data']['total_count'] == 3
    assert client.get(f'/api/schema?connection_id={cid}&table=t').get_json()['success']


def test_driver_refuses_writes_even_if_the_guard_is_bypassed(sqlite_path):
    from db_connectors.sqlite import SQLiteConnector
    c = SQLiteConnector({'type': 'sqlite', 'database': sqlite_path, 'read_only': True})
    assert c.connect()
    assert c.execute_query('delete from t')['error']
    assert not c.insert_row('t', {'name': 'x'})[0]
    assert _rows(sqlite_path) == 3


def test_writable_connection_is_not_affected(client, sqlite_path):
    cid = _sqlite_conn(client, sqlite_path)
    assert client.post('/api/query', json={'connection_id': cid, 'query': "update t set name='z' where id = 1"}).get_json()['success']


def test_delete_without_where_needs_confirmation_and_changes_nothing_until_confirmed(client, sqlite_path):
    cid = _sqlite_conn(client, sqlite_path)
    r = client.post('/api/query', json={'connection_id': cid, 'query': 'delete from t'})
    assert r.status_code == 409 and r.get_json()['needs_confirmation'] and 'WHERE' in r.get_json()['reason']
    assert _rows(sqlite_path) == 3
    ok = client.post('/api/query', json={'connection_id': cid, 'query': 'delete from t', 'confirmed': True}).get_json()
    assert ok['success'] and _rows(sqlite_path) == 0


def test_scoped_delete_runs_without_confirmation(client, sqlite_path):
    cid = _sqlite_conn(client, sqlite_path)
    assert client.post('/api/query', json={'connection_id': cid, 'query': 'delete from t where id = 1'}).get_json()['success']
    assert _rows(sqlite_path) == 2


# --- /api/columns ------------------------------------------------------------------------

def test_columns_endpoint_all_and_subset(client, conn_id):
    allcols = client.get(f'/api/columns?connection_id={conn_id}').get_json()['columns']
    assert allcols['t'] == ['id', 'name', 'v']
    one = client.get(f'/api/columns?connection_id={conn_id}&tables=t').get_json()['columns']
    assert one == {'t': ['id', 'name', 'v']}


def test_columns_endpoint_handles_unknown_and_not_connected(client, conn_id):
    r = client.get(f'/api/columns?connection_id={conn_id}&tables=nope').get_json()
    assert r['success'] and not r['columns'].get('nope')
    assert client.get('/api/columns?connection_id=missing').status_code == 400


def test_tables_report_whether_counts_are_estimates(client, conn_id):
    t = client.get(f'/api/tables?connection_id={conn_id}').get_json()['tables'][0]
    assert t['rows'] == 3 and t['rows_estimated'] is False


def test_sqlite_skips_exact_counts_for_large_files(client, sqlite_path, monkeypatch):
    from db_connectors.sqlite import SQLiteConnector
    monkeypatch.setattr(SQLiteConnector, 'EXACT_COUNT_MAX_BYTES', 1)
    cid = client.post('/api/connections', json={'name': 'x', 'type': 'sqlite', 'database': sqlite_path}).get_json()['id']
    client.post('/api/connect', json={'id': cid})
    t = client.get(f'/api/tables?connection_id={cid}').get_json()['tables'][0]
    assert t['rows'] is None and t['name'] == 't'


# --- following foreign keys ------------------------------------------------------------------------

@pytest.fixture
def fk_conn(client, sqlite_path):
    import sqlite3
    c = sqlite3.connect(sqlite_path)
    c.execute('create table kids(id integer primary key, t_id integer references t(id), note text)')
    c.executemany('insert into kids(t_id, note) values (?, ?)', [(1, 'a'), (1, 'b'), (2, 'c')])
    c.commit()
    c.close()
    return _sqlite_conn(client, sqlite_path)


def test_relations_endpoint_lists_tables_and_foreign_keys(client, fk_conn):
    body = client.get(f'/api/relations?connection_id={fk_conn}').get_json()
    assert body['success'] and {t['name'] for t in body['tables']} == {'t', 'kids'}
    assert body['relations'] == [{'table': 'kids', 'column': 't_id', 'referenced_table': 't', 'referenced_column': 'id'}]


def test_exact_filter_returns_only_matching_rows(client, fk_conn, sqlite_path):
    r = client.get('/api/data', query_string=dict(connection_id=fk_conn, table='kids', database=sqlite_path,
                                                  where_column='t_id', where_value='1')).get_json()['data']
    assert r['total_count'] == 2 and sorted(x['note'] for x in r['rows']) == ['a', 'b']


def test_exact_filter_is_not_a_substring_match(client, fk_conn, sqlite_path):
    r = client.get('/api/data', query_string=dict(connection_id=fk_conn, table='kids', database=sqlite_path,
                                                  where_column='id', where_value='1')).get_json()['data']
    assert r['total_count'] == 1   # id 1 only, not ids that merely contain a 1


def test_exact_filter_combines_with_search_and_rejects_unknown_columns(client, fk_conn, sqlite_path):
    base = dict(connection_id=fk_conn, table='kids', database=sqlite_path)
    both = client.get('/api/data', query_string={**base, 'where_column': 't_id', 'where_value': '1', 'search': 'b'}).get_json()['data']
    assert both['total_count'] == 1
    evil = client.get('/api/data', query_string={**base, 'where_column': 't_id; DROP TABLE kids --', 'where_value': '1'})
    assert evil.status_code == 400
    assert client.get('/api/data', query_string=base).get_json()['data']['total_count'] == 3


# --- column insights over HTTP -------------------------------------------------------------------------------------

def test_profile_endpoint(client, conn_id, sqlite_path):
    r = client.get('/api/profile', query_string=dict(connection_id=conn_id, table='t', column='v', database=sqlite_path)).get_json()
    p = r['profile']
    assert r['success'] and (p['total'], p['distinct'], p['min'], p['max']) == (3, 3, 1.0, 3.0) and len(p['histogram']) == 10


def test_profile_endpoint_validates_the_column_against_the_schema(client, conn_id, sqlite_path):
    base = dict(connection_id=conn_id, table='t', database=sqlite_path)
    assert client.get('/api/profile', query_string={**base, 'column': 'nope'}).status_code == 400
    assert client.get('/api/profile', query_string={**base, 'column': 'v; DROP TABLE t'}).status_code == 400
    assert client.get('/api/profile', query_string=base).status_code == 400
    assert get_data(client, conn_id, sqlite_path).get_json()['data']['total_count'] == 3


def test_profile_endpoint_samples_big_tables(client, conn_id, sqlite_path, monkeypatch):
    monkeypatch.setattr(db, 'PROFILE_SAMPLE_THRESHOLD', 2)   # the 3-row table now counts as "big"
    monkeypatch.setattr(db, 'PROFILE_SAMPLE_ROWS', 2)
    p = client.get('/api/profile', query_string=dict(connection_id=conn_id, table='t', column='name', database=sqlite_path)).get_json()['profile']
    assert p['sampled'] and p['total'] == 2


def test_profile_endpoint_needs_a_connection_and_a_sql_database(client):
    assert client.get('/api/profile?connection_id=none&table=t&column=c').status_code == 400
