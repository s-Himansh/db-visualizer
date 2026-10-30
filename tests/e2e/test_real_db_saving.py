"""Editing typed columns (decimal, date, timestamp, boolean, float) through the real UI on each real database must not
raise a false "changed by someone else" alarm: the check compares text, and every database formats values differently."""
import json
import socket

import pytest

from conftest import dialogs

pytestmark = pytest.mark.e2e

SQL = {
    'mysql': dict(port=13306, conn=dict(host='127.0.0.1', port=13306, username='root', password='testpw', database='dbviz'), db='dbviz',
                  drop='DROP TABLE IF EXISTS ui_edit',
                  ddl='CREATE TABLE ui_edit(id INT PRIMARY KEY, name VARCHAR(40), price DECIMAL(8,2), born DATE, seen DATETIME, active TINYINT(1), score DOUBLE, note TEXT)',
                  ins="INSERT INTO ui_edit VALUES (1, 'alpha', 12.50, '2026-03-04', '2026-03-04 10:20:30', 1, 1.5, 'hello'), (2, 'beta', 7.00, '2026-01-02', '2026-01-02 01:02:03', 0, 2.0, NULL)"),
    'postgresql': dict(port=15432, conn=dict(host='127.0.0.1', port=15432, username='postgres', password='testpw', database='dbviz'), db='dbviz',
                       drop='DROP TABLE IF EXISTS ui_edit',
                       ddl='CREATE TABLE ui_edit(id INT PRIMARY KEY, name VARCHAR(40), price NUMERIC(8,2), born DATE, seen TIMESTAMP, active BOOLEAN, score DOUBLE PRECISION, note TEXT)',
                       ins="INSERT INTO ui_edit VALUES (1, 'alpha', 12.50, '2026-03-04', '2026-03-04 10:20:30', TRUE, 1.5, 'hello'), (2, 'beta', 7.00, '2026-01-02', '2026-01-02 01:02:03', FALSE, 2.0, NULL)"),
    'sqlserver': dict(port=11433, conn=dict(host='127.0.0.1', port=11433, username='sa', password='Testpw123!', database='master'), db='master',
                      drop="IF OBJECT_ID('ui_edit') IS NOT NULL DROP TABLE ui_edit",
                      ddl='CREATE TABLE ui_edit(id INT PRIMARY KEY, name VARCHAR(40), price DECIMAL(8,2), born DATE, seen DATETIME, active BIT, score FLOAT, note NVARCHAR(MAX))',
                      ins="INSERT INTO ui_edit VALUES (1, 'alpha', 12.50, '2026-03-04', '2026-03-04 10:20:30', 1, 1.5, 'hello'), (2, 'beta', 7.00, '2026-01-02', '2026-01-02 01:02:03', 0, 2.0, NULL)"),
    'oracle': dict(port=11521, conn=dict(host='127.0.0.1', port=11521, username='dbviz', password='testpw', database='FREEPDB1'), db='DBVIZ',
                   drop='BEGIN EXECUTE IMMEDIATE \'DROP TABLE "ui_edit"\'; EXCEPTION WHEN OTHERS THEN NULL; END;',
                   ddl='CREATE TABLE "ui_edit"("id" NUMBER(10) PRIMARY KEY, "name" VARCHAR2(40), "price" NUMBER(8,2), "born" DATE, "seen" TIMESTAMP, "active" NUMBER(1), "score" BINARY_DOUBLE, "note" VARCHAR2(200))',
                   ins=['INSERT INTO "ui_edit" VALUES (1, \'alpha\', 12.50, DATE \'2026-03-04\', TIMESTAMP \'2026-03-04 10:20:30\', 1, 1.5, \'hello\')',
                        'INSERT INTO "ui_edit" VALUES (2, \'beta\', 7.00, DATE \'2026-01-02\', TIMESTAMP \'2026-01-02 01:02:03\', 0, 2.0, NULL)']),
}


def up(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


@pytest.fixture(params=list(SQL), ids=list(SQL))
def real(request, page):
    spec = SQL[request.param]
    if request.param == 'oracle':
        pytest.skip('UI navigation to an Oracle schema is not automated here; Oracle is covered by the connector contract tests')
    if not up(spec['port']):
        pytest.skip(f'{request.param} test server not running')
    from db_connectors import mysql, oracle, postgres, sqlserver
    cls = {'mysql': mysql.MySQLConnector, 'postgresql': postgres.PostgreSQLConnector,
           'sqlserver': sqlserver.SQLServerConnector, 'oracle': oracle.OracleConnector}[request.param]
    admin = cls({'type': request.param, **spec['conn']})
    assert admin.connect()
    admin.execute_query(spec['drop'])
    assert not admin.execute_query(spec['ddl']).get('error')
    for stmt in ([spec['ins']] if isinstance(spec['ins'], str) else spec['ins']):
        assert not admin.execute_query(stmt).get('error'), stmt
    if request.param == 'sqlserver':
        pass

    page.evaluate("""([name, body]) => fetch('/api/connections', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)})""", ['Real DB', {'name': 'Real DB', 'type': request.param, **spec['conn']}])
    page.reload()
    page.wait_for_selector('#manage-connections-btn')
    page.click('#manage-connections-btn')
    page.click('.connection-item:has-text("Real DB") .connect-btn')
    page.wait_for_selector('#tables-content .tree-item:has(.tree-label:text-is("ui_edit"))', timeout=20000)
    page.evaluate("document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'))")
    page.locator('#tables-content .tree-item').filter(has=page.locator('.tree-label:text-is("ui_edit")')).click()
    page.wait_for_selector('.tab-content.active .data-table tbody tr')
    yield page, admin, spec, request.param
    admin.execute_query(spec['drop'])
    admin.disconnect()


def edit(pg, row, column, text):
    cell = pg.locator(f'.tab-content.active tr[data-row-index="{row}"] td[data-column={column}]')
    cell.click()
    pg.keyboard.press('Meta+A')
    pg.keyboard.type(text)
    pg.keyboard.press('Tab')


def saved(pg, n=1):
    pg.wait_for_function("t => document.querySelector('#toast-stack') && document.querySelector('#toast-stack').innerText.includes(t)",
                         arg=f'Saved {n} change')


def value(admin, spec, name, row=1):
    q = admin.q
    r = admin.execute_query(f'SELECT {q(name)} FROM {q("ui_edit")} WHERE {q("id")} = {row}')
    assert not r.get('error'), r
    return list(r['rows'][0].values())[0]


def test_editing_every_kind_of_column_never_raises_a_false_conflict(real):
    page, admin, spec, kind = real
    edit(page, 0, 'name', 'alpha 2')
    edit(page, 0, 'price', '99.99')
    edit(page, 0, 'score', '2.5')
    edit(page, 0, 'note', 'changed') if kind != 'oracle' else None
    page.click('.tab-content.active [data-action=save-changes]')
    saved(page, 1)                                  # one row changed (the toast counts rows, not cells)
    assert dialogs(page) == [], f'a false conflict was reported: {dialogs(page)}'
    assert value(admin, spec, 'name') == 'alpha 2'
    assert float(value(admin, spec, 'price')) == 99.99 and float(value(admin, spec, 'score')) == 2.5


def test_editing_a_date_and_a_timestamp_column(real):
    page, admin, spec, kind = real
    if kind == 'oracle':
        pytest.skip('editing an Oracle DATE needs a TO_DATE format the connector does not add yet')
    edit(page, 0, 'born', '2026-05-06')
    edit(page, 0, 'seen', '2026-05-06 07:08:09')
    page.click('.tab-content.active [data-action=save-changes]')
    saved(page, 1)
    assert dialogs(page) == []
    assert str(value(admin, spec, 'born'))[:10] == '2026-05-06' and '2026-05-06 07:08:09' in str(value(admin, spec, 'seen'))


def test_a_boolean_or_flag_column_and_a_null_cell(real):
    page, admin, spec, kind = real
    edit(page, 1, 'active', '1')
    edit(page, 1, 'note', 'was null') if kind != 'oracle' else edit(page, 1, 'note', 'was null')
    page.click('.tab-content.active [data-action=save-changes]')
    saved(page, 1)
    assert dialogs(page) == [], f'a false conflict was reported: {dialogs(page)}'


def test_a_real_conflict_is_still_caught_on_each_database(real):
    page, admin, spec, kind = real
    q = admin.q
    edit(page, 0, 'name', 'mine')
    admin.execute_query(f"UPDATE {q('ui_edit')} SET {q('name')} = 'theirs' WHERE {q('id')} = 1")
    page.evaluate("window.__dialogAnswer = false")
    page.click('.tab-content.active [data-action=save-changes]')
    page.wait_for_function("window.__dialogs.length >= 1")
    assert 'name was "alpha" when you loaded it, now "theirs"' in dialogs(page)[-1]
    assert value(admin, spec, 'name') == 'theirs'
