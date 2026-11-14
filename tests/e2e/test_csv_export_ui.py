"""CSV a person opens in a spreadsheet must not run formulas hidden in the data."""
import csv

import pytest

from conftest import open_query_tab

pytestmark = pytest.mark.e2e


def test_exported_query_results_do_not_carry_live_formulas(connected):
    open_query_tab(connected)
    sql = "select '=HYPERLINK(\"http://evil.example\",\"x\")' as a, '-5' as b, -5 as c, 'plain' as d, '@SUM(1)' as e"
    connected.evaluate("sql => document.querySelector('.tab-content.active .CodeMirror').CodeMirror.setValue(sql)", sql)
    connected.click('.tab-content.active [data-action=execute]')
    connected.wait_for_selector('.tab-content.active .results-grid table')
    with connected.expect_download(timeout=5000) as dl:
        connected.click('.tab-content.active [data-action=export-csv]')
    rows = list(csv.reader(open(dl.value.path(), encoding='utf-8')))
    assert rows[1] == ['\'=HYPERLINK("http://evil.example","x")', '-5', '-5', 'plain', "'@SUM(1)"]


def test_exported_table_csv_is_protected_too(connected):
    connected.locator('#tables-content .tree-item').filter(has=connected.locator('.tree-label:text-is("customers")')).click()
    connected.wait_for_selector('.tab-content.active .data-table tbody tr')
    with connected.expect_download(timeout=5000) as dl:
        connected.click('.tab-content.active [data-action=export-table-csv]')
    text = open(dl.value.path(), encoding='utf-8').read()
    assert not any(line.split(',')[0].startswith(('=', '+', '@')) for line in text.splitlines())
