"""Reading CSV files: encodings, delimiters, quoting, bad shapes, and column mapping."""
import pytest

import csv_import as ci
from csv_import import ImportProblem


# ---- encodings ---------------------------------------------------------------------------------------------

def test_utf8_with_and_without_a_byte_order_mark():
    assert ci.decode('é,ü\n'.encode('utf-8')) == ('é,ü\n', 'utf-8-sig')
    text, enc = ci.decode(b'\xef\xbb\xbfid,name\n')                      # what Excel's "CSV UTF-8" writes
    assert text == 'id,name\n' and enc == 'utf-8-sig'                      # the mark is not part of the first header


def test_windows_excel_files_are_read_as_cp1252():
    text, enc = ci.decode('café;€5\n'.encode('cp1252'))
    assert text == 'café;€5\n' and enc == 'cp1252'


def test_a_binary_file_is_refused():
    with pytest.raises(ImportProblem, match='text file'):
        ci.decode(b'PK\x03\x04\x00\x00\x00\x00 an xlsx file')


def test_the_bytes_cp1252_does_not_define_still_decode():
    assert ci.decode(b'a\x81b')[1] == 'latin-1'


# ---- delimiters ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('sep', [',', ';', '\t', '|'])
def test_the_delimiter_is_detected(sep):
    text = f'id{sep}name{sep}city\n1{sep}Ann{sep}Oslo\n2{sep}Bo{sep}Rome\n'
    assert ci.detect_delimiter(text) == sep


def test_a_semicolon_file_with_commas_in_the_values():
    assert ci.detect_delimiter('id;note\n1;"a, b, c"\n2;"d, e"\n') == ';'


def test_a_one_column_file_falls_back_to_comma():
    assert ci.detect_delimiter('name\nAnn\nBo\n') == ','


# ---- parsing ------------------------------------------------------------------------------------------------

def test_quotes_doubled_quotes_and_line_breaks_inside_a_value():
    rows = ci.parse('id,note\r\n1,"he said ""hi"""\r\n2,"line one\nline two"\r\n3,plain\r\n', ',')
    assert rows == [['id', 'note'], ['1', 'he said "hi"'], ['2', 'line one\nline two'], ['3', 'plain']]


def test_blank_lines_are_skipped_and_a_missing_final_newline_is_fine():
    assert ci.parse('a,b\n\n1,2\n\n3,4', ',') == [['a', 'b'], ['1', '2'], ['3', '4']]


def test_leading_zeros_and_spaces_are_kept_as_written():
    assert ci.parse('zip,code\n00123, 7 \n', ',')[1] == ['00123', ' 7 ']


def test_an_oversized_cell_is_a_clear_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(ci, 'MAX_CELL_CHARS', 50)
    with pytest.raises(ImportProblem, match='could not be read'):
        ci.parse('a\n' + 'x' * 100 + '\n', ',')


# ---- analyze ------------------------------------------------------------------------------------------------

def test_a_normal_file():
    a = ci.analyze(b'id, name ,city\n1,Ann,Oslo\n2,Bo,Rome\n')
    assert a['headers'] == ['id', 'name', 'city'] and a['rows'] == [['1', 'Ann', 'Oslo'], ['2', 'Bo', 'Rome']]
    assert a['delimiter'] == ',' and a['encoding'] == 'utf-8-sig' and a['problems'] == [] and a['has_header'] is True


def test_without_a_header_row_every_row_is_data():
    a = ci.analyze(b'1,Ann\n2,Bo\n', has_header=False)
    assert a['headers'] == ['Column 1', 'Column 2'] and len(a['rows']) == 2


def test_the_delimiter_can_be_forced():
    a = ci.analyze(b'a;b\n1;2\n', delimiter=',')                          # wrong on purpose: one column
    assert a['headers'] == ['a;b']


@pytest.mark.parametrize('raw,message', [(b'', 'empty'), (b'  \n\n ', 'empty'), (b'\n\n', 'empty')])
def test_files_with_nothing_to_import(raw, message):
    with pytest.raises(ImportProblem, match=message):
        ci.analyze(raw)


def test_a_header_with_no_data_is_a_problem_to_show_not_a_refusal():
    a = ci.analyze(b'Hal Nine,hal@example.com\n')
    assert a['rows'] == [] and a['headers'] == ['Hal Nine', 'hal@example.com'] and 'no data rows' in a['problems'][0]
    assert 'untick' in a['problems'][0]
    assert ci.analyze(b'Hal Nine,hal@example.com\n', has_header=False)['rows'] == [['Hal Nine', 'hal@example.com']]


def test_rows_with_the_wrong_number_of_values_are_reported_by_row_number():
    a = ci.analyze(b'a,b,c\n1,2,3\n4,5\n6,7,8,9\n10,11,12\n')
    assert a['problems'] == ['Row 2 has 2 values but there are 3 columns.', 'Row 3 has 4 values but there are 3 columns.']


def test_a_single_value_is_not_pluralised():
    assert ci.analyze(b'a,b\n1\n')['problems'] == ['Row 1 has 1 value but there are 2 columns.']


def test_many_bad_rows_are_summarised(monkeypatch):
    raw = b'a,b\n' + b'1\n' * 12
    problems = ci.analyze(raw)['problems']
    assert len(problems) == ci.MAX_PROBLEMS_SHOWN + 1 and '7 more rows' in problems[-1]


def test_too_many_rows(monkeypatch):
    monkeypatch.setattr(ci, 'MAX_IMPORT_ROWS', 3)
    a = ci.analyze(b'a\n1\n2\n3\n4\n')
    assert any('4 rows' in p and 'At most 3' in p for p in a['problems'])


def test_too_large_a_file(monkeypatch):
    monkeypatch.setattr(ci, 'MAX_IMPORT_BYTES', 10)
    with pytest.raises(ImportProblem, match='larger than'):
        ci.analyze(b'a,b\n1,2\n3,4\n')


# ---- mapping --------------------------------------------------------------------------------------------------

def test_names_match_ignoring_case_spaces_and_hyphens():
    m = ci.suggest_mapping(['id', 'first_name', 'Zip-Code', 'notes'], ['ID', 'First Name', 'zip code', 'other'])
    assert m == {'id': 0, 'first_name': 1, 'Zip-Code': 2, 'notes': None}


def test_the_first_of_two_same_named_columns_wins():
    assert ci.suggest_mapping(['a'], ['a', 'A'])['a'] == 0


def test_a_valid_mapping_drops_the_unmapped():
    assert ci.check_mapping({'id': 0, 'name': 2, 'skip': None, 'blank': ''}, ['id', 'name', 'skip', 'blank'], 3) == {'id': 0, 'name': 2}


@pytest.mark.parametrize('mapping,message', [
    ({'nope': 0}, 'no column called "nope"'), ({'id': 5}, 'does not exist'), ({'id': -1}, 'does not exist'),
    ({'id': True}, 'does not exist'), ({'id': '1'}, 'does not exist'), ({'id': None}, 'at least one'), ({}, 'at least one'),
    (None, 'Choose which'), (['id'], 'Choose which')])
def test_unusable_mappings_are_refused(mapping, message):
    with pytest.raises(ImportProblem, match=message):
        ci.check_mapping(mapping, ['id', 'name'], 2)


def test_a_hostile_column_name_can_never_reach_sql():
    with pytest.raises(ImportProblem):
        ci.check_mapping({'id"; drop table t; --': 0}, ['id', 'name'], 1)


# ---- operations -------------------------------------------------------------------------------------------------

def test_one_insert_per_row_with_only_the_mapped_columns():
    ops = ci.build_operations([['1', 'Ann', 'x'], ['2', 'Bo', 'y']], {'id': 0, 'name': 1}, empty_as_null=True)
    assert ops == [{'op': 'insert', 'data': {'id': '1', 'name': 'Ann'}}, {'op': 'insert', 'data': {'id': '2', 'name': 'Bo'}}]


def test_empty_values_are_null_or_empty_text_as_asked():
    rows = [['1', '', ' ']]
    assert ci.build_operations(rows, {'a': 1, 'b': 2}, True)[0]['data'] == {'a': None, 'b': ' '}     # a space is not empty
    assert ci.build_operations(rows, {'a': 1, 'b': 2}, False)[0]['data'] == {'a': '', 'b': ' '}


def test_values_stay_text():
    assert ci.build_operations([['007', '1e3', 'true', '2026-03-04']], {'a': 0, 'b': 1, 'c': 2, 'd': 3}, True)[0]['data'] == \
        {'a': '007', 'b': '1e3', 'c': 'true', 'd': '2026-03-04'}


def test_the_same_file_column_can_feed_two_table_columns():
    assert ci.build_operations([['x']], {'a': 0, 'b': 0}, True)[0]['data'] == {'a': 'x', 'b': 'x'}


# ---- dates ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('value,expected', [
    ('2026-03-04', '2026-03-04'), ('2026-03-04 10:20:30', '2026-03-04 10:20:30'), ('2026-03-04T10:20:30', '2026-03-04 10:20:30'),
    ('2026-03-04 10:20', '2026-03-04 10:20'), ('2026-03-04 10:20:30.123456', '2026-03-04 10:20:30.123456'),
    ('2026-03-04T10:20:30Z', '2026-03-04 10:20:30Z'), ('2026-03-04 10:20:30+05:30', '2026-03-04 10:20:30+05:30'),
    ('  2026-03-04  ', '2026-03-04'), ('2024-02-29', '2024-02-29')])
def test_iso_dates_are_accepted_and_tidied(value, expected):
    assert ci.normalize_date(value) == expected


@pytest.mark.parametrize('value', ['04/03/2026', '4 Mar 2026', '03-04-2026', '2026/03/04', '20260304', '2026-3-4', '2026-02-30',
                                   '2025-02-29', '2026-13-01', '2026-00-10', '2026-03-04 25:00:00', '2026-03-04 10:61', 'yesterday', 'abc', ''])
def test_everything_else_is_refused(value):
    assert ci.normalize_date(value) is None


@pytest.mark.parametrize('column_type,expected', [
    ('date', True), ('DATE', True), ('datetime', True), ('datetime2', True), ('timestamp', True), ('TIMESTAMP(6)', True),
    ('timestamp without time zone', True), ('timestamp with time zone', True), ('datetimeoffset', True), ('smalldatetime', True),
    ('time', False), ('integer', False), ('varchar(20)', False), ('text', False), (None, False), ('', False)])
def test_which_column_types_hold_dates(column_type, expected):
    assert ci.is_date_type(column_type) is expected


def test_date_problems_name_the_row_and_column():
    rows = [['1', '2026-03-04'], ['2', '04/03/2026'], ['3', ''], ['4', 'soon']]
    problems = ci.date_problems(rows, {'id': 0, 'born': 1}, {'born'})
    assert len(problems) == 2 and problems[0].startswith('Row 2, "born": "04/03/2026"') and problems[1].startswith('Row 4')
    assert 'wrong way round' in problems[0]


def test_empty_dates_and_unmapped_date_columns_are_not_problems():
    assert ci.date_problems([['1', '']], {'id': 0, 'born': 1}, {'born'}) == []
    assert ci.date_problems([['1', 'junk']], {'id': 0}, {'born'}) == []


def test_many_bad_dates_are_summarised():
    problems = ci.date_problems([['x']] * 9, {'d': 0}, {'d'})
    assert len(problems) == ci.MAX_PROBLEMS_SHOWN + 1 and '4 more values' in problems[-1]


def test_operations_use_the_tidied_date_but_leave_other_columns_alone():
    ops = ci.build_operations([['2026-03-04T10:20:30', '2026-03-04T9']], {'seen': 0, 'note': 1}, True, {'seen'})
    assert ops[0]['data'] == {'seen': '2026-03-04 10:20:30', 'note': '2026-03-04T9'}
