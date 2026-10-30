"""One behavioural contract, run against every connector.

If a connector cannot do something by design (Cassandra has no LIKE), declare it in the backend's
`unsupported` set with the reason, so the gap is documented and visible rather than silently untested."""
import pytest

from conftest import HOST, reachable
from db_connectors.cassandra import CassandraConnector
from db_connectors.mongodb import MongoDBConnector
from db_connectors.oracle import OracleConnector
from db_connectors.mysql import MySQLConnector
from db_connectors.postgres import PostgreSQLConnector
from db_connectors.sqlite import SQLiteConnector
from db_connectors.sqlserver import SQLServerConnector

pytestmark = pytest.mark.integration

NAMES = ['Alice', 'Bob', 'Carol', 'Dave', 'Erin', 'Frank']
COUNTRIES = ['IN', 'US', 'DE']


class Backend:
    def __init__(self, id, cls, port, params, ddl=None, unsupported=(), pk=True, db='dbviz'):
        self.id, self.cls, self.port, self.db, self.pk = id, cls, port, db, pk
        self.params = {'type': id, 'host': HOST, 'port': port, 'database': db, **params}
        self.ddl = ddl or []
        self.unsupported = set(unsupported)


BACKENDS = [
    Backend('sqlite', SQLiteConnector, 0, {'host': None, 'port': None}, db=':memory:', ddl=[
        'CREATE TABLE people(id INTEGER PRIMARY KEY, name TEXT, country TEXT, score REAL)']),
    Backend('mysql', MySQLConnector, 13306, {'username': 'root', 'password': 'testpw'}, ddl=[
        'DROP TABLE IF EXISTS people',
        'CREATE TABLE people(id INT PRIMARY KEY, name VARCHAR(50), country VARCHAR(5), score DECIMAL(6,2))']),
    Backend('postgresql', PostgreSQLConnector, 15432, {'username': 'postgres', 'password': 'testpw'}, ddl=[
        'DROP TABLE IF EXISTS people',
        'CREATE TABLE people(id INT PRIMARY KEY, name VARCHAR(50), country VARCHAR(5), score NUMERIC(6,2))']),
    Backend('sqlserver', SQLServerConnector, 11433, {'username': 'sa', 'password': 'Testpw123!', 'database': 'master'}, db='master', ddl=[
        "IF OBJECT_ID('people') IS NOT NULL DROP TABLE people",
        'CREATE TABLE people(id INT PRIMARY KEY, name VARCHAR(50), country VARCHAR(5), score DECIMAL(6,2))']),
    # a MongoDB collection that does not exist is simply empty, so there is no "missing table" error
    # Oracle folds unquoted names to UPPER CASE; the connector always quotes, so the test objects are created lower-case
    Backend('oracle', OracleConnector, 11521, {'username': 'dbviz', 'password': 'testpw', 'database': 'FREEPDB1'}, db='DBVIZ', ddl=[
        "BEGIN EXECUTE IMMEDIATE 'DROP TABLE \"kids\"'; EXCEPTION WHEN OTHERS THEN NULL; END;",
        "BEGIN EXECUTE IMMEDIATE 'DROP TABLE \"people\"'; EXCEPTION WHEN OTHERS THEN NULL; END;",
        'CREATE TABLE "people"("id" NUMBER(10) PRIMARY KEY, "name" VARCHAR2(50), "country" VARCHAR2(5), "score" NUMBER(6,2))']),
    Backend('mongodb', MongoDBConnector, 27018, {}, pk=False, unsupported={'missing_table'}),
    Backend('cassandra', CassandraConnector, 19042, {}, ddl=[
        'DROP TABLE IF EXISTS dbviz.people',
        'CREATE TABLE dbviz.people(id int PRIMARY KEY, name text, country text, score decimal)'],
        unsupported={'search', 'sort'}),  # CQL has no LIKE, and cannot ORDER BY a non-clustering column
]


def new_connector(b, **override):
    c = b.cls({**b.params, **override})
    assert c.connect(), f'{b.id}: could not connect'
    return c


@pytest.fixture(scope='module', params=BACKENDS, ids=lambda b: b.id)
def env(request):
    b = request.param
    if b.port and not reachable(b.port):
        pytest.skip(f'{b.id} server not running on {b.port}')
    if b.id == 'cassandra':  # the keyspace must exist before a connection can use it
        admin = b.cls({**b.params, 'database': None, 'keyspace': None})
        assert admin.connect()
        admin.execute_query("CREATE KEYSPACE IF NOT EXISTS dbviz WITH replication = {'class':'SimpleStrategy','replication_factor':1}")
        admin.disconnect()
    conn = new_connector(b)
    for stmt in b.ddl:
        r = conn.execute_query(stmt)
        assert not r.get('error'), f'{b.id} DDL failed: {stmt}: {r["error"]}'
    if b.id == 'mongodb':
        conn.connection[b.db]['people'].drop()
    for i in range(1, 31):
        ok, msg = conn.insert_row('people', {
            'id': i, 'name': f'{NAMES[i % 6]}{i}', 'country': COUNTRIES[i % 3], 'score': i * 1.5}, b.db)
        assert ok, f'{b.id}: seed insert failed: {msg}'
    yield b, conn
    conn.disconnect()


def data(conn, b, **kw):
    return conn.get_table_data('people', b.db, **kw)


def ids(result):
    return sorted(int(r['id']) for r in result['rows'])


def needs(b, feature):
    if feature in b.unsupported:
        pytest.skip(f'{b.id} does not support {feature} by design')


# ---- connection & metadata -----------------------------------------------------

def test_test_connection_and_state(env):
    b, conn = env
    ok, _ = new_connector(b).test_connection()
    assert ok and conn.is_connected()


def test_bad_credentials_fail_cleanly(env):
    b, _ = env
    if not b.port or b.id in ('mongodb', 'cassandra'):
        pytest.skip('server runs without auth')
    bad = b.cls({**b.params, 'password': 'definitely-wrong'})
    ok, msg = bad.test_connection()
    assert not ok and msg


def test_lists_database_and_table(env):
    b, conn = env
    tables = [t['name'] for t in conn.get_tables(b.db)]
    assert 'people' in tables


def test_schema_has_columns_and_primary_key(env):
    b, conn = env
    cols = {c['name']: c for c in conn.get_schema('people', b.db)['columns']}
    assert {'id', 'name', 'country', 'score'} <= set(cols)
    if b.pk:
        assert cols['id']['primary_key'] is True and cols['name']['primary_key'] is False


# ---- reading ---------------------------------------------------------------------

def test_total_and_paging(env):
    b, conn = env
    first = data(conn, b, limit=10, offset=0)
    assert first['total_count'] == 30 and len(first['rows']) == 10 and first['has_more'] is True
    last = data(conn, b, limit=10, offset=20)
    assert len(last['rows']) == 10 and last['has_more'] is False
    assert set(ids(first)).isdisjoint(ids(last))


def test_columns_reported(env):
    b, conn = env
    assert {'id', 'name', 'country', 'score'} <= set(data(conn, b, limit=1)['columns'])


def test_sort_both_directions(env):
    b, conn = env
    needs(b, 'sort')
    asc = data(conn, b, limit=5, sort_by='id', sort_order='ASC')['rows']
    desc = data(conn, b, limit=5, sort_by='id', sort_order='DESC')['rows']
    assert [int(r['id']) for r in asc] == [1, 2, 3, 4, 5]
    assert [int(r['id']) for r in desc] == [30, 29, 28, 27, 26]


def test_exact_filter(env):
    b, conn = env
    r = data(conn, b, filters={'country': 'IN'}, limit=100)
    assert r['total_count'] == 10 and {x['country'] for x in r['rows']} == {'IN'}


def test_search_every_column_case_insensitive(env):
    b, conn = env
    needs(b, 'search')
    r = data(conn, b, filters={'search_term': 'ALICE'}, limit=100)
    assert r['total_count'] == 5 and all('Alice' in x['name'] for x in r['rows'])


def test_search_specific_column(env):
    b, conn = env
    needs(b, 'search')
    r = data(conn, b, filters={'search_term': 'US', 'search_column': 'country'}, limit=100)
    assert r['total_count'] == 10
    assert data(conn, b, filters={'search_term': 'US', 'search_column': 'name'}, limit=100)['total_count'] == 0  # 'US' is in no name


def test_search_numeric_column(env):
    b, conn = env
    needs(b, 'search')
    assert data(conn, b, filters={'search_term': '45', 'search_column': 'score'}, limit=100)['total_count'] >= 1


def test_search_no_match_and_special_characters(env):
    b, conn = env
    needs(b, 'search')
    for term in ('zzzqq', "o'brien", '100%', 'a_b', '"; drop table people; --'):
        assert data(conn, b, filters={'search_term': term}, limit=10)['total_count'] == 0, term
    assert data(conn, b, limit=1)['total_count'] == 30  # table intact


def test_search_combined_with_paging(env):
    b, conn = env
    needs(b, 'search')
    p1 = data(conn, b, filters={'search_term': 'alice'}, limit=3, offset=0)
    p2 = data(conn, b, filters={'search_term': 'alice'}, limit=3, offset=3)
    assert p1['total_count'] == 5 and len(p1['rows']) == 3 and p1['has_more']
    assert len(p2['rows']) == 2 and not p2['has_more']


def test_missing_table_raises_instead_of_empty(env):
    b, conn = env
    needs(b, 'missing_table')
    with pytest.raises(Exception):
        conn.get_table_data('no_such_table', b.db, limit=5)


# ---- queries ---------------------------------------------------------------------

def test_execute_select(env):
    b, conn = env
    if b.id == 'mongodb':
        pytest.skip('mongodb takes JSON queries, covered in test_mongo_query')
    q = conn.q
    table = f'{q("dbviz")}.{q("people")}' if b.id == 'cassandra' else q('people')
    sql = f'SELECT {q("id")}, {q("name")} FROM {table} WHERE {q("id")} = 1'
    r = conn.execute_query(sql)
    assert not r.get('error'), r.get('error')
    assert r['row_count'] == 1 and [str(c) for c in r['columns']] == ['id', 'name']


def test_bad_query_reports_error_without_raising(env):
    b, conn = env
    if b.id == 'mongodb':
        pytest.skip('mongodb takes JSON queries')
    r = conn.execute_query('SELECT * FROM definitely_missing')
    assert r.get('error')


# ---- writing ---------------------------------------------------------------------

def test_insert_update_delete_roundtrip(env):
    b, conn = env
    ok, msg = conn.insert_row('people', {'id': 900, 'name': 'Zed', 'country': 'XX', 'score': 1.5}, b.db)
    assert ok, msg
    assert data(conn, b, filters={'country': 'XX'})['total_count'] == 1
    ok, msg = conn.update_row('people', {'id': 900}, {'name': 'Zed2'}, b.db)
    assert ok, msg
    assert data(conn, b, filters={'country': 'XX'})['rows'][0]['name'] == 'Zed2'
    ok, msg = conn.delete_row('people', {'id': 900}, b.db)
    assert ok, msg
    assert data(conn, b, filters={'country': 'XX'})['total_count'] == 0
    assert data(conn, b, limit=1)['total_count'] == 30  # the whole row is gone, not just one column


def test_values_with_quotes_survive_writing(env):
    b, conn = env
    ok, msg = conn.insert_row('people', {'id': 901, 'name': "O'Brien \"Q\" %_", 'country': 'QQ', 'score': 2}, b.db)
    assert ok, msg
    assert data(conn, b, filters={'country': 'QQ'})['rows'][0]['name'] == "O'Brien \"Q\" %_"
    conn.delete_row('people', {'id': 901}, b.db)


def test_update_without_match_does_not_touch_other_rows(env):
    b, conn = env
    conn.update_row('people', {'id': 424242}, {'name': 'nobody'}, b.db)
    assert data(conn, b, filters={'name': 'nobody'})['total_count'] == 0


def test_connection_still_works_after_a_failed_statement(env):
    b, conn = env
    if b.id == 'mongodb':
        pytest.skip('no transactions to poison')
    conn.execute_query('SELECT * FROM definitely_missing')
    with pytest.raises(Exception):
        conn.get_table_data('no_such_table', b.db, limit=5)
    assert data(conn, b, limit=1)['total_count'] == 30
    assert conn.get_schema('people', b.db)['columns']


def test_read_only_connection_is_refused_by_the_server_itself(env):
    """Bypass the application's query guard and talk to the connector directly: the database must say no."""
    b, conn = env
    if b.id not in ('postgresql', 'mysql', 'sqlite'):
        pytest.skip(f'{b.id}: no driver-level read-only mode; the application-level guard applies')
    if b.id == 'sqlite':
        pytest.skip('covered in tests/test_api.py (the :memory: database here is private to one connection)')
    ro = new_connector(b, read_only=True)
    assert data(ro, b, limit=1)['total_count'] == 30                      # reads still work
    assert ro.execute_query('DELETE FROM people WHERE id = 1')['error']   # the server refuses the write
    assert not ro.insert_row('people', {'id': 777, 'name': 'x', 'country': 'ZZ', 'score': 1}, b.db)[0]
    assert not ro.update_row('people', {'id': 1}, {'name': 'hacked'}, b.db)[0]
    assert not ro.delete_row('people', {'id': 1}, b.db)[0]
    assert data(conn, b, filters={'id': 1})['rows'][0]['name'] != 'hacked'
    assert data(conn, b, limit=1)['total_count'] == 30
    ro.disconnect()


# ---- listing must stay cheap on big databases -------------------------------------------

def _statements_run(conn):
    """Server-side count of statements this connection has executed (MySQL 'Questions')."""
    cur = conn.connection.cursor()
    cur.execute("SHOW SESSION STATUS LIKE 'Questions'")
    return int(list(cur.fetchone().values())[1])


def test_listing_tables_does_not_scan_every_table(env):
    """get_tables used to run SELECT COUNT(*) on each table: a full scan per table on connect."""
    b, conn = env
    if b.id != 'mysql':
        pytest.skip('statement counter is MySQL-specific; the other drivers already read catalog estimates')
    extra = [f'zz_listing_{i}' for i in range(25)]
    for name in extra:
        conn.execute_query(f'CREATE TABLE IF NOT EXISTS {name}(id INT PRIMARY KEY)')
    try:
        before = _statements_run(conn)
        tables = conn.get_tables(b.db)
        used = _statements_run(conn) - before
        assert {'people', *extra} <= {t['name'] for t in tables}
        assert used <= 4, f'listing {len(tables)} tables ran {used} statements (a COUNT(*) per table?)'
    finally:
        for name in extra:
            conn.execute_query(f'DROP TABLE IF EXISTS {name}')


def test_table_listing_marks_counts_as_estimates(env):
    b, conn = env
    if b.id in ('mongodb', 'cassandra'):
        pytest.skip('no catalog row counts')
    people = next(t for t in conn.get_tables(b.db) if t['name'] == 'people')
    assert 'rows_estimated' in people
    if b.id == 'sqlite':
        assert people['rows'] == 30 and people['rows_estimated'] is False


# ---- column names for autocomplete -------------------------------------------------------

def test_get_columns_for_chosen_tables(env):
    b, conn = env
    cols = conn.get_columns(b.db, ['people'])
    assert set(cols) == {'people'}
    assert {'id', 'name', 'country', 'score'} <= set(cols['people'])
    if b.pk and b.id != 'cassandra':   # catalog order = column order; Cassandra lists partition key first
        assert cols['people'] == ['id', 'name', 'country', 'score']


def test_get_columns_ignores_unknown_and_empty_selections(env):
    b, conn = env
    assert 'no_such_table' not in conn.get_columns(b.db, ['people', 'no_such_table']) or \
        conn.get_columns(b.db, ['people', 'no_such_table'])['no_such_table'] == []
    if b.id in ('mysql', 'postgresql', 'sqlserver', 'oracle'):
        assert conn.get_columns(b.db, []) == {}


def test_get_columns_without_a_filter_includes_the_table(env):
    b, conn = env
    assert 'people' in conn.get_columns(b.db)


def test_getting_columns_for_many_tables_is_one_statement(env):
    b, conn = env
    if b.id != 'mysql':
        pytest.skip('statement counter is MySQL-specific')
    extra = [f'zz_cols_{i}' for i in range(25)]
    for name in extra:
        conn.execute_query(f'CREATE TABLE IF NOT EXISTS {name}(id INT PRIMARY KEY, label VARCHAR(5))')
    try:
        before = _statements_run(conn)
        cols = conn.get_columns(b.db, extra)
        used = _statements_run(conn) - before
        assert all(cols[n] == ['id', 'label'] for n in extra)
        assert used <= 3, f'{len(extra)} tables took {used} statements'
    finally:
        for name in extra:
            conn.execute_query(f'DROP TABLE IF EXISTS {name}')


# ---- foreign keys (schema map and link-following) -----------------------------------------------

FK_DDL = {
    'sqlite': ['DROP TABLE IF EXISTS kids',
               'CREATE TABLE kids(id INTEGER PRIMARY KEY, person_id INTEGER REFERENCES people(id))'],
    'mysql': ['DROP TABLE IF EXISTS kids',
              'CREATE TABLE kids(id INT PRIMARY KEY, person_id INT, FOREIGN KEY (person_id) REFERENCES people(id))'],
    'postgresql': ['DROP TABLE IF EXISTS kids',
                   'CREATE TABLE kids(id INT PRIMARY KEY, person_id INT REFERENCES people(id))'],
    'oracle': ["BEGIN EXECUTE IMMEDIATE 'DROP TABLE \"kids\"'; EXCEPTION WHEN OTHERS THEN NULL; END;",
               'CREATE TABLE "kids"("id" NUMBER(10) PRIMARY KEY, "person_id" NUMBER(10) REFERENCES "people"("id"))'],
    'sqlserver': ["IF OBJECT_ID('kids') IS NOT NULL DROP TABLE kids",
                  'CREATE TABLE kids(id INT PRIMARY KEY, person_id INT REFERENCES people(id))'],
}


@pytest.fixture
def with_kids(env):
    b, conn = env
    if b.id not in FK_DDL:
        pytest.skip(f'{b.id} has no foreign keys')
    for stmt in FK_DDL[b.id]:
        assert not conn.execute_query(stmt).get('error'), stmt
    yield b, conn
    for stmt in {'oracle': ['DROP TABLE "kids"'], 'sqlserver': ['DROP TABLE kids']}.get(b.id, ['DROP TABLE IF EXISTS kids']):
        conn.execute_query(stmt)


def test_get_relations_lists_every_foreign_key(with_kids):
    b, conn = with_kids
    rel = conn.get_relations(b.db)
    assert {'table': 'kids', 'column': 'person_id', 'referenced_table': 'people', 'referenced_column': 'id'} in rel


def test_get_relations_is_one_statement_on_mysql(with_kids):
    b, conn = with_kids
    if b.id != 'mysql':
        pytest.skip('statement counter is MySQL-specific')
    before = _statements_run(conn)
    conn.get_relations(b.db)
    assert _statements_run(conn) - before <= 3


def test_get_relations_is_empty_without_foreign_keys(env):
    b, conn = env
    if b.id in ('mongodb', 'cassandra'):
        assert conn.get_relations(b.db) == []


# ---- column insights -----------------------------------------------------------------------------------------------

SQL_PROFILE = ('sqlite', 'mysql', 'postgresql', 'sqlserver', 'oracle')


def profile(conn, b, column, **kw):
    return conn.profile_column('people', column, b.db, **kw)


def test_profile_a_text_column(env):
    b, conn = env
    if b.id not in SQL_PROFILE:
        pytest.skip('column insights are SQL-only')
    p = profile(conn, b, 'country')
    assert (p['total'], p['non_null'], p['nulls'], p['distinct']) == (30, 30, 0, 3)
    assert (p['min'], p['max']) == ('DE', 'US')
    assert sorted((t['value'], t['count']) for t in p['top']) == [('DE', 10), ('IN', 10), ('US', 10)]
    assert 'histogram' not in p and not p['sampled']


def test_profile_a_numeric_column_includes_average_and_a_histogram(env):
    b, conn = env
    if b.id not in SQL_PROFILE:
        pytest.skip('column insights are SQL-only')
    p = profile(conn, b, 'id')
    assert (p['total'], p['distinct'], p['min'], p['max']) == (30, 30, 1, 30)
    assert float(p['avg']) == 15.5
    expected = [0] * 10
    for v in range(1, 31):
        expected[min(int((v - 1) / ((30 - 1) / 10)), 9)] += 1   # same formula, computed here
    assert [h['count'] for h in p['histogram']] == expected and sum(expected) == 30
    assert p['histogram'][0]['from'] == 1 and p['histogram'][-1]['to'] == 30


def test_profile_counts_nulls(env):
    b, conn = env
    if b.id not in SQL_PROFILE:
        pytest.skip('column insights are SQL-only')
    num, txt = {'oracle': ('NUMBER(10)', 'VARCHAR2(20)')}.get(b.id, ('INT', 'VARCHAR(20)'))
    q = conn.q
    drop = {'oracle': [f'BEGIN EXECUTE IMMEDIATE \'DROP TABLE "profiled"\'; EXCEPTION WHEN OTHERS THEN NULL; END;'],
            'sqlserver': ["IF OBJECT_ID('profiled') IS NOT NULL DROP TABLE profiled"]}.get(b.id, ['DROP TABLE IF EXISTS profiled'])
    for stmt in drop:
        conn.execute_query(stmt)
    assert not conn.execute_query(f'CREATE TABLE {q("profiled")}({q("id")} {num} PRIMARY KEY, {q("note")} {txt})').get('error')
    try:
        for i in range(1, 11):
            conn.insert_row('profiled', {'id': i, 'note': None if i <= 4 else ('a' if i % 2 else 'b')}, b.db)
        p = conn.profile_column('profiled', 'note', b.db)
        assert (p['total'], p['non_null'], p['nulls'], p['distinct']) == (10, 6, 4, 2)
        assert sorted((t['value'], t['count']) for t in p['top']) == [('a', 3), ('b', 3)]   # nulls are not a "value"
    finally:
        for stmt in drop:
            conn.execute_query(stmt)


def test_profile_can_read_just_a_sample(env):
    b, conn = env
    if b.id not in SQL_PROFILE:
        pytest.skip('column insights are SQL-only')
    p = profile(conn, b, 'country', sample=10)
    assert p['sampled'] is True and p['sample_rows'] == 10 and p['total'] == 10


def test_profile_rejects_hostile_column_names_and_leaves_the_table_alone(env):
    b, conn = env
    if b.id not in SQL_PROFILE:
        pytest.skip('column insights are SQL-only')
    for evil in ('id; DROP TABLE people', 'id" FROM people --', 'id` , (SELECT 1)'):
        with pytest.raises(Exception):
            profile(conn, b, evil)
    assert data(conn, b, limit=1)['total_count'] == 30


def test_profile_is_not_offered_for_non_sql_databases(env):
    b, conn = env
    if b.id in SQL_PROFILE:
        pytest.skip('SQL database')
    assert conn.SUPPORTS_PROFILE is False
    with pytest.raises(NotImplementedError):
        conn.profile_column('people', 'id', b.db)
