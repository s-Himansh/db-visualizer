"""Inferring undeclared relationships on the real SQL databases. The data check is plain SQL, and every dialect limits,
quotes, joins and compares text in its own way, so it is tested on each."""
import socket

import pytest

import db
import relationship_inference as ri

SPECS = {
    'mysql': dict(port=13306, params=dict(host='127.0.0.1', port=13306, username='root', password='testpw', database='dbviz'), schema='dbviz', i='INT', t='VARCHAR(40)'),
    'postgresql': dict(port=15432, params=dict(host='127.0.0.1', port=15432, username='postgres', password='testpw', database='dbviz'), schema='dbviz', i='INT', t='VARCHAR(40)'),
    'sqlserver': dict(port=11433, params=dict(host='127.0.0.1', port=11433, username='sa', password='Testpw123!', database='master'), schema='master', i='INT', t='VARCHAR(40)'),
    'oracle': dict(port=11521, params=dict(host='127.0.0.1', port=11521, username='dbviz', password='testpw', database='FREEPDB1'), schema='DBVIZ', i='NUMBER(10)', t='VARCHAR2(40)'),
}
TABLES = ['zlogs', 'zreviews', 'zorders', 'zevents', 'zdevices', 'zcustomers']


def up(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def fill(conn, schema, table, rows):
    ops = [{'op': 'insert', 'data': r} for r in rows]
    for start in range(0, len(ops), 1000):
        result = conn.apply_batch(table, ops[start:start + 1000], schema)
        assert result['success'], result


@pytest.fixture(params=list(SPECS), ids=list(SPECS))
def real(request, client):
    kind, spec = request.param, SPECS[request.param]
    if not up(spec['port']):
        pytest.skip(f'{kind} test server not running')
    cid = client.post('/api/connections', json={'name': kind, 'type': kind, **spec['params']}).get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']
    conn, schema, i, t = db.active_connections[cid], spec['schema'], spec['i'], spec['t']
    q = conn.q

    def drop_all():
        for table in TABLES:
            if kind == 'oracle':
                conn.execute_query(f'BEGIN EXECUTE IMMEDIATE \'DROP TABLE "{table}"\'; EXCEPTION WHEN OTHERS THEN NULL; END;')
            elif kind == 'sqlserver':
                conn.execute_query(f"IF OBJECT_ID('{table}') IS NOT NULL DROP TABLE {table}")
            else:
                conn.execute_query(f'DROP TABLE IF EXISTS {table}')

    drop_all()
    for ddl in [f'CREATE TABLE {q("zcustomers")}({q("id")} {i} PRIMARY KEY, {q("name")} {t})',
                f'CREATE TABLE {q("zdevices")}({q("id")} {t} PRIMARY KEY)',
                f'CREATE TABLE {q("zorders")}({q("id")} {i} PRIMARY KEY, {q("zcustomer_id")} {i})',
                f'CREATE TABLE {q("zreviews")}({q("id")} {i} PRIMARY KEY, {q("zcustomer_id")} {i})',
                f'CREATE TABLE {q("zevents")}({q("id")} {i} PRIMARY KEY, {q("zdevice_id")} {t})',
                f'CREATE TABLE {q("zlogs")}({q("id")} {i} PRIMARY KEY, {q("zcustomer_id")} {t})']:
        made = conn.execute_query(ddl)
        assert not made.get('error'), (ddl, made)
    fill(conn, schema, 'zcustomers', [{'id': n, 'name': f'c{n}'} for n in range(1, 61)])
    fill(conn, schema, 'zdevices', [{'id': f'dev-{n:03d}'} for n in range(1, 41)])
    fill(conn, schema, 'zorders', [{'id': n, 'zcustomer_id': n % 60 + 1} for n in range(1, 301)])
    fill(conn, schema, 'zreviews', [{'id': n, 'zcustomer_id': (n % 60 + 1) if n % 5 else 5000 + n} for n in range(1, 101)])   # a fifth orphans
    fill(conn, schema, 'zevents', [{'id': n, 'zdevice_id': f'dev-{n % 40 + 1:03d}'} for n in range(1, 201)])
    fill(conn, schema, 'zlogs', [{'id': n, 'zcustomer_id': f'word{n}'} for n in range(1, 21)])
    yield client, cid, conn, schema, kind
    drop_all()


def suggestions(conn, schema):
    result = ri.infer(conn, schema, [], [])
    return {(s['table'], s['column']): s for s in result['suggestions']}, result


def test_a_clean_numeric_relationship_is_found_with_exact_counts(real):
    client, cid, conn, schema, kind = real
    got, _ = suggestions(conn, schema)
    s = got[('zorders', 'zcustomer_id')]
    assert (s['referenced_table'], s['referenced_column']) == ('zcustomers', 'id')
    assert s['distinct'] == 60 and s['matched'] == 60 and s['containment'] == 1.0 and s['confidence'] == 'high'


def test_a_text_keyed_relationship_is_found(real):
    client, cid, conn, schema, kind = real
    got, _ = suggestions(conn, schema)
    s = got[('zevents', 'zdevice_id')]
    assert s['referenced_table'] == 'zdevices' and s['distinct'] == 40 and s['matched'] == 40


def test_orphans_are_counted(real):
    client, cid, conn, schema, kind = real
    s = suggestions(conn, schema)[0][('zreviews', 'zcustomer_id')]
    # 80 reviews point at a real customer but only 48 distinct ones (n % 60 repeats); 20 point at nobody
    assert s['distinct'] == 68 and s['matched'] == 48 and s['orphans'] == 20 and s['confidence'] == 'low'


def test_orphan_rows_are_the_rows_that_point_at_nothing(real):
    client, cid, conn, schema, kind = real
    found = conn.orphan_rows('zreviews', 'zcustomer_id', 'zcustomers', 'id', schema, 5)
    assert found['total_count'] == 20 and len(found['rows']) == 5       # 20 of the 100 reviews point at nobody
    assert all(r['zcustomer_id'] >= 5000 for r in found['rows'])


def test_text_in_a_column_named_like_a_number_reference_is_left_alone(real):
    client, cid, conn, schema, kind = real
    assert ('zlogs', 'zcustomer_id') not in suggestions(conn, schema)[0]


def test_the_check_looks_at_a_bounded_sample_of_a_big_table(real):
    client, cid, conn, schema, kind = real
    fill(conn, schema, 'zorders', [{'id': n, 'zcustomer_id': n % 60 + 1} for n in range(1000, 4000)])        # 3,300 rows in all
    result = conn.check_reference('zorders', 'zcustomer_id', 'zcustomers', 'id', schema, 500)
    assert result == {'distinct': 60, 'matched': 60}
    assert conn.check_reference('zorders', 'zcustomer_id', 'zcustomers', 'id', schema, 5)['distinct'] <= 5


def test_the_same_answers_come_through_the_api(real):
    client, cid, conn, schema, kind = real
    body = client.get(f'/api/relations/inferred?connection_id={cid}&database={schema}').get_json()
    assert body['success'] is True
    mine = {(s['table'], s['column']): s for s in body['suggestions'] if s['table'].startswith('z')}
    assert set(mine) == {('zorders', 'zcustomer_id'), ('zreviews', 'zcustomer_id'), ('zevents', 'zdevice_id')}


def test_accepting_one_makes_the_grid_links_and_map_see_it(real):
    client, cid, conn, schema, kind = real
    rel = {'table': 'zorders', 'column': 'zcustomer_id', 'referenced_table': 'zcustomers', 'referenced_column': 'id'}
    assert client.post('/api/relations/decision', json={'connection_id': cid, 'database': schema, 'action': 'accept', 'relation': rel}).get_json()['success']
    served = client.get(f'/api/relations?connection_id={cid}&database={schema}').get_json()['relations']
    assert {**rel, 'virtual': True} in served
    client.post('/api/relations/decision', json={'connection_id': cid, 'database': schema, 'action': 'forget', 'relation': rel})
