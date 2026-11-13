"""Whole-table export, search across every table and the schema the map reads, on every real database."""
import csv
import io
import json

import pytest

import db
from test_connectors import BACKENDS, env  # noqa: F401  (env is the fixture)
from test_relationship_real import real  # noqa: F401  (the four SQL servers, seeded with z* tables)

pytestmark = pytest.mark.integration


def export(client, cid, schema, table, fmt):
    return client.get('/api/export', query_string=dict(connection_id=cid, database=schema, table=table, format=fmt))


def test_sql_export_has_every_row_and_runs_back_into_the_database(real):
    client, cid, conn, schema, kind = real
    r = export(client, cid, schema, 'zcustomers', 'sql')
    assert r.status_code == 200 and r.headers['X-Export-Rows'] == '60'
    lines = r.get_data(as_text=True).splitlines()
    assert len(lines) == 60 and all(l.startswith('INSERT INTO ') and l.endswith(');') for l in lines)
    # the file must be replayable: empty the table, run the export, and the same rows are back
    conn.execute_query(f'DELETE FROM {conn.table_ref("zcustomers", schema)}')
    for line in lines:
        made = conn.execute_query(line.rstrip(';'))
        assert not made.get('error'), (line, made)
    assert conn.get_table_data('zcustomers', schema, limit=1)['total_count'] == 60


def test_csv_and_json_export_cover_the_whole_table(real):
    client, cid, conn, schema, kind = real
    rows = list(csv.reader(io.StringIO(export(client, cid, schema, 'zorders', 'csv').get_data(as_text=True))))
    assert len(rows) == 301 and [c.lower() for c in rows[0]] == ['id', 'zcustomer_id']     # 300 rows and a header
    body = json.loads(export(client, cid, schema, 'zorders', 'json').get_data(as_text=True))
    assert len(body) == 300


def test_export_quotes_awkward_text(real):
    client, cid, conn, schema, kind = real
    conn.apply_batch('zcustomers', [{'op': 'insert', 'data': {'id': 999, 'name': "O'Brien, \"Jr\""}}], schema)
    sql = export(client, cid, schema, 'zcustomers', 'sql').get_data(as_text=True)
    assert "'O''Brien, \"Jr\"'" in sql
    text = export(client, cid, schema, 'zcustomers', 'csv').get_data(as_text=True)
    assert any(r[1] == "O'Brien, \"Jr\"" for r in csv.reader(io.StringIO(text)))


def test_search_finds_a_value_in_the_right_tables(real):
    client, cid, conn, schema, kind = real
    body = client.get('/api/search', query_string=dict(connection_id=cid, database=schema, term='dev-005')).get_json()
    assert body['success'], body
    found = {r['table'].lower(): r['total'] for r in body['results']}
    assert found == {'zdevices': 1, 'zevents': 5}         # the device itself, and the 5 events that use it
    assert body['scanned'] == body['tables'] and body['failed'] == 0


def test_search_is_not_case_sensitive_and_finds_nothing_when_absent(real):
    client, cid, conn, schema, kind = real
    upper = client.get('/api/search', query_string=dict(connection_id=cid, database=schema, term='C17')).get_json()
    assert upper['success'] and 'zcustomers' in [r['table'].lower() for r in upper['results']], (kind, upper)
    none = client.get('/api/search', query_string=dict(connection_id=cid, database=schema, term='no-such-value-xyz')).get_json()
    assert none['success'] and none['results'] == []


def test_schema_reports_primary_keys_and_types_for_the_map(real):
    client, cid, conn, schema, kind = real
    columns = client.get('/api/schema', query_string=dict(connection_id=cid, database=schema, table='zcustomers')).get_json()['schema']['columns']
    by_name = {c['name'].lower(): c for c in columns}
    assert by_name['id']['primary_key'] and not by_name['name']['primary_key'] and by_name['name']['type']


# ---- every connector, including the ones that are not SQL ---------------------------------------------------------

@pytest.fixture
def registered(env):  # noqa: F811
    b, conn = env
    db.active_connections['qa'] = db.SerializedConnector(conn)
    yield b, 'qa'
    db.active_connections.pop('qa', None)


def test_csv_and_json_export_work_for_every_database(registered, client):
    b, cid = registered
    r = export(client, cid, b.db, 'people', 'json')
    assert r.status_code == 200 and len(json.loads(r.get_data(as_text=True))) == 30, b.id
    r = export(client, cid, b.db, 'people', 'csv')
    assert len(list(csv.reader(io.StringIO(r.get_data(as_text=True))))) == 31, b.id


def test_sql_export_and_search_say_no_for_databases_that_are_not_sql(registered, client):
    b, cid = registered
    if b.id in ('sqlite', 'mysql', 'postgresql', 'sqlserver', 'oracle'):
        pytest.skip('a SQL database')
    assert export(client, cid, b.db, 'people', 'sql').status_code == 400
    assert client.get('/api/search', query_string=dict(connection_id=cid, database=b.db, term='Alice')).status_code == 400
