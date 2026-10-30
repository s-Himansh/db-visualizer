import pytest

from db_connectors.safety import check, statements


def ro(db, q):
    return check(db, q).read_only


def danger(db, q):
    return check(db, q).destructive


@pytest.mark.parametrize('q', [
    'SELECT * FROM t', 'select 1', '  \n SELECT id FROM t WHERE name = \'delete me\'',
    'WITH x AS (SELECT 1) SELECT * FROM x', 'SHOW TABLES', 'DESCRIBE t', 'desc t',
    'EXPLAIN SELECT * FROM t', 'VALUES (1),(2)', 'TABLE t',
    'select update_count, deleted_at from t',                 # words that merely contain keywords
    'select "update", `delete` from t',                       # quoted identifiers
    "select 'a;drop table t' as x",                           # semicolon inside a string
    '-- drop table t\nSELECT 1', '/* delete from t */ SELECT 1',
    'SELECT 1;', 'SELECT 1; SELECT 2',
])
def test_reads_are_allowed(q):
    assert ro('postgresql', q), check('postgresql', q)


@pytest.mark.parametrize('q', [
    'INSERT INTO t VALUES (1)', 'UPDATE t SET a=1', 'DELETE FROM t', 'DROP TABLE t', 'TRUNCATE t',
    'ALTER TABLE t ADD c int', 'CREATE TABLE x(a int)', 'REPLACE INTO t VALUES (1)', 'GRANT ALL ON t TO u',
    'CALL do_things()', 'EXEC sp_who', 'MERGE INTO t USING s ON 1=1 WHEN MATCHED THEN DELETE',
    'SELECT 1; DROP TABLE t',                                 # a write hidden after a read
    'select 1;delete from t',
    'WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d',  # data-modifying CTE
    'SELECT * INTO backup FROM t',                            # creates a table
    "SELECT * FROM t INTO OUTFILE '/tmp/x'",                  # writes a file
    'SELECT * FROM t FOR UPDATE', 'SELECT * FROM t LOCK IN SHARE MODE',
    'EXPLAIN ANALYZE DELETE FROM t',
    'UPDATE t SET a = 1 -- SELECT 1',                         # a read-looking comment
    '/* SELECT */ DELETE FROM t',
])
def test_writes_are_blocked_in_read_only(q):
    v = check('postgresql', q)
    assert not v.read_only and v.why_not, q


def test_explain_only_where_the_driver_also_enforces_read_only():
    assert ro('mysql', 'EXPLAIN SELECT 1') and ro('sqlite', 'EXPLAIN SELECT 1')
    assert not ro('sqlserver', 'EXPLAIN SELECT 1') and not ro('oracle', 'EXPLAIN PLAN FOR SELECT 1')


@pytest.mark.parametrize('q', ['DELETE FROM t', 'delete from t;', 'UPDATE t SET a = 1', 'update t set a=1 where 1=1',
                               'UPDATE t SET a=1 WHERE true', 'DELETE FROM t -- where id = 1',
                               "UPDATE t SET note = 'where x'"])
def test_update_delete_without_real_where_needs_confirmation(q):
    assert danger('mysql', q), q


@pytest.mark.parametrize('q', ['DELETE FROM t WHERE id = 1', 'update t set a=1 where id in (1,2)',
                               'UPDATE t SET a = 1 WHERE a = 0 AND b = 2', 'SELECT * FROM t', 'INSERT INTO t VALUES (1)'])
def test_scoped_statements_do_not_need_confirmation(q):
    assert not danger('mysql', q), q


@pytest.mark.parametrize('q', ['DROP TABLE t', 'drop database x', 'TRUNCATE TABLE t', 'ALTER TABLE t DROP COLUMN c',
                               'SELECT 1; DROP TABLE t'])
def test_structure_changes_always_need_confirmation(q):
    assert danger('postgresql', q), q


def test_statement_splitting_ignores_semicolons_in_literals_and_comments():
    assert statements("select 'a;b'; /* ; */ select 2 -- ;\n") == ["select ''", 'select 2']


def test_empty_query_is_harmless():
    assert ro('mysql', '') and ro('mysql', '  ;  ') and not danger('mysql', '')


@pytest.mark.parametrize('cmd', ['GET k', 'get k', 'HGETALL h', 'KEYS *', 'TTL k', 'LRANGE l 0 -1', 'INFO'])
def test_redis_reads(cmd):
    assert ro('redis', cmd)


@pytest.mark.parametrize('cmd', ['SET k v', 'DEL k', 'FLUSHALL', 'FLUSHDB', 'EXPIRE k 1', 'CONFIG SET x y', 'EVAL "x" 0', 'SHUTDOWN'])
def test_redis_writes_blocked(cmd):
    assert not ro('redis', cmd)


def test_redis_flush_needs_confirmation():
    assert danger('redis', 'FLUSHALL') and danger('redis', 'flushdb') and not danger('redis', 'DEL k')


def test_mongodb_query_runner_only_reads():
    assert ro('mongodb', '{"collection": "c"}')
