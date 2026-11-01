"""CSV import against the real SQL databases, through the HTTP API. Every value in a CSV is text, so each database has to
convert it itself: this checks that it does, that a bad row undoes the whole import, and that dates are never misread."""
import io
import json
import socket
import time

import pytest

import db
from db_connectors.base import as_shown

SPECS = {
    'mysql': dict(port=13306, params=dict(host='127.0.0.1', port=13306, username='root', password='testpw', database='dbviz'), schema='dbviz',
                  ddl='CREATE TABLE csv_real(id INT PRIMARY KEY, name VARCHAR(60), price DECIMAL(8,2), born DATE, seen DATETIME, flag TINYINT(1), score DOUBLE, note TEXT)'),
    'postgresql': dict(port=15432, params=dict(host='127.0.0.1', port=15432, username='postgres', password='testpw', database='dbviz'), schema='dbviz',
                       ddl='CREATE TABLE csv_real(id INT PRIMARY KEY, name VARCHAR(60), price NUMERIC(8,2), born DATE, seen TIMESTAMP, flag BOOLEAN, score DOUBLE PRECISION, note TEXT)'),
    'sqlserver': dict(port=11433, params=dict(host='127.0.0.1', port=11433, username='sa', password='Testpw123!', database='master'), schema='master',
                      ddl='CREATE TABLE csv_real(id INT PRIMARY KEY, name VARCHAR(60), price DECIMAL(8,2), born DATE, seen DATETIME, flag BIT, score FLOAT, note NVARCHAR(MAX))'),
    'oracle': dict(port=11521, params=dict(host='127.0.0.1', port=11521, username='dbviz', password='testpw', database='FREEPDB1'), schema='DBVIZ',
                   ddl='CREATE TABLE "csv_real"("id" NUMBER(10) PRIMARY KEY, "name" VARCHAR2(60), "price" NUMBER(8,2), "born" DATE, "seen" TIMESTAMP, "flag" NUMBER(1), "score" BINARY_DOUBLE, "note" VARCHAR2(400))'),
}
HEADER = 'id,name,price,born,seen,flag,score,note\n'
ALL = {c: i for i, c in enumerate(['id', 'name', 'price', 'born', 'seen', 'flag', 'score', 'note'])}


def up(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


@pytest.fixture(params=list(SPECS), ids=list(SPECS))
def real(request, client):
    kind, spec = request.param, SPECS[request.param]
    if not up(spec['port']):
        pytest.skip(f'{kind} test server not running')
    cid = client.post('/api/connections', json={'name': kind, 'type': kind, **spec['params']}).get_json()['id']
    assert client.post('/api/connect', json={'id': cid}).get_json()['success']
    conn = db.active_connections[cid]
    q = conn.q
    drop = 'BEGIN EXECUTE IMMEDIATE \'DROP TABLE "csv_real"\'; EXCEPTION WHEN OTHERS THEN NULL; END;' if kind == 'oracle' else \
        ('DROP TABLE IF EXISTS csv_real' if kind != 'sqlserver' else "IF OBJECT_ID('csv_real') IS NOT NULL DROP TABLE csv_real")
    conn.execute_query(drop)
    made = conn.execute_query(spec['ddl'])
    assert not made.get('error'), made
    yield client, cid, conn, spec['schema'], kind
    conn.execute_query(drop)


def count(conn, schema):
    return int(conn.get_table_data('csv_real', schema, limit=1)['total_count'])


def upload(client, cid, schema, text, mapping=ALL, **extra):
    form = {'connection_id': cid, 'database': schema, 'table': 'csv_real', 'mapping': json.dumps(mapping),
            'file': (io.BytesIO(text.encode('utf-8')), 'f.csv'), **extra}
    return client.post('/api/import', data=form, content_type='multipart/form-data')


def test_typed_columns_receive_text_and_the_database_converts_it(real):
    client, cid, conn, schema, kind = real
    text = HEADER + '1,"Zoë ""Z"" O\'Brien",12.50,2026-03-04,2026-03-04T10:20:30,1,1.5,"line one\nline two"\n2,Plain,7,2026-01-02,2026-01-02 01:02:03,0,2,\n3,Blank,,,,,,\n'
    r = upload(client, cid, schema, text)
    assert r.get_json() == {'success': True, 'imported': 3, 'dry_run': False}, r.get_json()
    rows = {int(x['id']): x for x in conn.get_table_data('csv_real', schema, limit=10)['rows']}
    assert rows[1]['name'] == 'Zoë "Z" O\'Brien' and float(rows[1]['price']) == 12.5 and float(rows[1]['score']) == 1.5
    assert as_shown(rows[1]['born'])[:10] == '2026-03-04' and as_shown(rows[1]['seen'])[:19] == '2026-03-04 10:20:30'
    assert str(rows[1]['flag']).lower() in ('1', 'true') and rows[1]['note'] == 'line one\nline two'
    assert str(rows[2]['flag']).lower() in ('0', 'false') and float(rows[2]['price']) == 7.0
    assert all(rows[3][c] in (None, '') for c in ('price', 'born', 'seen', 'flag', 'score', 'note'))      # empty -> NULL


def test_a_bad_value_in_the_last_row_undoes_the_whole_file(real):
    client, cid, conn, schema, kind = real
    text = HEADER + ''.join(f'{i},Row {i},1.5,2026-03-04,2026-03-04 10:00:00,1,1,x\n' for i in range(1, 4)) + '4,Bad,not a number,2026-03-04,2026-03-04 10:00:00,1,1,x\n'
    r = upload(client, cid, schema, text)
    body = r.get_json()
    assert r.status_code == 422 and body['row'] == 4 and body['rolled_back'] is True and body['error'].startswith('Row 4:')
    assert count(conn, schema) == 0
    assert upload(client, cid, schema, HEADER + '9,After,1,2026-03-04,2026-03-04 10:00:00,1,1,x\n').get_json()['imported'] == 1   # still usable


def test_a_duplicate_key_names_the_row_and_changes_nothing(real):
    client, cid, conn, schema, kind = real
    row = lambda i: f'{i},n,1,2026-03-04,2026-03-04 10:00:00,1,1,x\n'
    assert upload(client, cid, schema, HEADER + row(5)).get_json()['success']
    r = upload(client, cid, schema, HEADER + row(6) + row(7) + row(5))
    assert r.status_code == 422 and r.get_json()['row'] == 3 and count(conn, schema) == 1


def test_a_dry_run_changes_nothing_and_the_real_run_then_works(real):
    client, cid, conn, schema, kind = real
    text = HEADER + '1,A,1,2026-03-04,2026-03-04 10:00:00,1,1,x\n2,B,2,2026-03-05,2026-03-05 10:00:00,0,2,y\n'
    assert upload(client, cid, schema, text, dry_run='true').get_json() == {'success': True, 'imported': 2, 'dry_run': True}
    assert count(conn, schema) == 0
    assert upload(client, cid, schema, text).get_json()['imported'] == 2 and count(conn, schema) == 2


def test_a_dry_run_finds_what_the_real_run_would_hit(real):
    client, cid, conn, schema, kind = real
    r = upload(client, cid, schema, HEADER + '1,A,abc,2026-03-04,2026-03-04 10:00:00,1,1,x\n', dry_run='true')
    assert r.status_code == 422 and r.get_json()['row'] == 1 and count(conn, schema) == 0


@pytest.mark.parametrize('bad', ['04/03/2026', '03/04/2026', '4 Mar 2026'])
def test_ambiguous_dates_never_reach_the_database(real, bad):
    """PostgreSQL and SQL Server would store 04/03/2026 as 3 April without complaint."""
    client, cid, conn, schema, kind = real
    r = upload(client, cid, schema, HEADER + f'1,A,1,{bad},2026-03-04 10:00:00,1,1,x\n')
    assert r.status_code == 400 and 'wrong way round' in r.get_json()['error'] and count(conn, schema) == 0


def test_the_same_file_loads_the_same_data_everywhere(real):
    client, cid, conn, schema, kind = real
    text = HEADER + '1,A,0.10,2026-12-31,2026-12-31 23:59:59,1,0.5,\n'
    assert upload(client, cid, schema, text).get_json()['success']
    [row] = conn.get_table_data('csv_real', schema, limit=5)['rows']
    assert as_shown(row['born'])[:10] == '2026-12-31' and as_shown(row['seen'])[:19] == '2026-12-31 23:59:59' and float(row['price']) == 0.1


def test_two_thousand_rows(real):
    client, cid, conn, schema, kind = real
    text = HEADER + ''.join(f'{i},Person {i},{i}.25,2026-03-04,2026-03-04 10:00:00,{i % 2},{i}.5,note {i}\n' for i in range(1, 2001))
    started = time.time()
    r = upload(client, cid, schema, text)
    took = time.time() - started
    assert r.get_json()['imported'] == 2000 and count(conn, schema) == 2000
    print(f'  [{kind}] 2000 rows in {took:.1f}s')
    assert took < 60


def test_oracle_gets_its_own_date_formats_back(real):
    client, cid, conn, schema, kind = real
    if kind != 'oracle':
        pytest.skip('only Oracle changes session formats for an import')
    read = lambda: conn.execute_query("SELECT parameter, value FROM nls_session_parameters WHERE parameter LIKE 'NLS_%FORMAT' ORDER BY parameter")['rows']
    before = read()
    upload(client, cid, schema, HEADER + '1,A,1,2026-03-04,2026-03-04 10:00:00,1,1,x\n')
    upload(client, cid, schema, HEADER + '2,A,abc,2026-03-04,2026-03-04 10:00:00,1,1,x\n')          # a failing import restores them too
    assert read() == before
