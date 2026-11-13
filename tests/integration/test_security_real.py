"""Hostile input to the export and search endpoints, on every real SQL database: a table name or a search term is data,
never SQL, and no file name or header is built from it unchecked."""
import pytest

import db
from test_relationship_real import real  # noqa: F401  (MySQL, PostgreSQL, SQL Server, Oracle with z* tables)

pytestmark = pytest.mark.integration

PAYLOADS = ["'; DROP TABLE zcustomers; --", "' OR '1'='1", '" OR ""="', "x') UNION SELECT 1 --", '%', '_', '\\', 'a\r\nSet-Cookie: x=1']


def tables_intact(client, cid, schema):
    names = {t['name'].lower() for t in client.get('/api/tables', query_string=dict(connection_id=cid, database=schema)).get_json()['tables']}
    return {'zcustomers', 'zorders', 'zdevices'} <= names


@pytest.mark.parametrize('payload', PAYLOADS)
def test_a_hostile_search_term_is_only_a_search_term(real, payload):
    client, cid, conn, schema, kind = real
    r = client.get('/api/search', query_string=dict(connection_id=cid, database=schema, term=payload))
    assert r.status_code in (200, 400), (kind, payload, r.status_code, r.get_data(as_text=True)[:200])
    body = r.get_json()
    assert 'Set-Cookie' not in str(r.headers)
    if r.status_code == 200:
        assert body['success'] and body['failed'] == 0, (kind, payload, body)
    assert tables_intact(client, cid, schema), (kind, payload)


@pytest.mark.parametrize('table', ["zcustomers; DROP TABLE zcustomers", "zcustomers' --", 'nope"\r\nX-Evil: 1', '../../etc/passwd', 'zcustomers UNION SELECT 1'])
def test_a_hostile_table_name_is_just_an_unknown_table(real, table):
    client, cid, conn, schema, kind = real
    for fmt in ('csv', 'json', 'sql'):
        r = client.get('/api/export', query_string=dict(connection_id=cid, database=schema, table=table, format=fmt))
        assert r.status_code in (400, 404, 500) or r.get_json() is None or not r.get_json().get('success', True), (kind, table, fmt)
        assert 'X-Evil' not in str(r.headers) and 'passwd' not in r.headers.get('Content-Disposition', '')
    assert tables_intact(client, cid, schema), (kind, table)


def test_a_table_name_with_quotes_exports_under_a_safe_file_name(real):
    client, cid, conn, schema, kind = real
    if kind == 'oracle':
        pytest.skip('Oracle forbids a double quote inside an identifier')
    name = 'z"odd;name'
    q = conn.q
    made = conn.execute_query(f'CREATE TABLE {q(name)} ({q("id")} INT PRIMARY KEY)')
    assert not made.get('error'), made
    try:
        conn.apply_batch(name, [{'op': 'insert', 'data': {'id': 1}}], schema)
        r = client.get('/api/export', query_string=dict(connection_id=cid, database=schema, table=name, format='csv'))
        assert r.status_code == 200
        disposition = r.headers['Content-Disposition']
        assert disposition == 'attachment; filename="z_odd_name.csv"', disposition
    finally:
        conn.execute_query(f'DROP TABLE {q(name)}')


def test_every_new_endpoint_refuses_a_caller_without_the_token_or_with_a_foreign_host(real):
    client, cid, conn, schema, kind = real
    bare = db.app.test_client()
    for path in ('/api/export', '/api/search', '/api/relations', '/api/relations/orphans'):
        assert bare.get(path, query_string=dict(connection_id=cid, table='zcustomers', term='ab')).status_code == 403, path
        assert client.get(path, headers={'Host': 'evil.example.com'}, query_string=dict(connection_id=cid, table='zcustomers', term='ab')).status_code == 403, path
