"""Read a CSV file and turn it into rows ready to insert into a table. No database or web code in here.

Everything in a CSV is text. Values go to the database as text and the database converts them (a "12" into an
integer column, a "2026-03-04" into a date column), so a value it cannot convert fails the import instead of being
guessed at. Column names from the file are never put into SQL: only columns that really exist in the table are used.
"""
import csv
import datetime
import io
import re
from typing import Any, Dict, List, Optional

MAX_IMPORT_ROWS = 10_000
MAX_IMPORT_BYTES = 20 * 1024 * 1024
MAX_CELL_CHARS = 1_000_000
DELIMITERS = {'comma': ',', 'semicolon': ';', 'tab': '\t', 'pipe': '|'}
MAX_PROBLEMS_SHOWN = 5

# Dates must be written year-month-day. "04/03/2026" is 4 March in Europe and 3 April in the US, and some databases
# (PostgreSQL, SQL Server) quietly pick one, so a file that mixes the two imports half wrong without any error.
ISO_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?)?\s*(?:Z|[+-]\d{2}(?::?\d{2})?)?$')


class ImportProblem(ValueError):
    """The file cannot be imported. The message is written for the user."""


def decode(raw: bytes):
    """(text, encoding). UTF-8 (with or without a byte order mark) first, then what Excel on Windows writes."""
    if b'\x00' in raw[:4096]:
        raise ImportProblem('This does not look like a text file. Export it from your spreadsheet as CSV (UTF-8) and try again.')
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1'), 'latin-1'      # every byte is valid in latin-1


def detect_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=''.join(DELIMITERS.values())).delimiter
    except csv.Error:
        return ','


def parse(text: str, delimiter: str) -> List[List[str]]:
    """Rows of text. Quotes, doubled quotes and line breaks inside quotes are honoured; blank lines are skipped."""
    csv.field_size_limit(MAX_CELL_CHARS)
    try:
        return [row for row in csv.reader(io.StringIO(text, newline=''), delimiter=delimiter, strict=False) if row]
    except csv.Error as e:
        raise ImportProblem(f'The file could not be read as CSV: {e}.') from e


def analyze(raw: bytes, delimiter: Optional[str] = None, has_header: bool = True) -> Dict[str, Any]:
    """Parse a file. Returns headers, the data rows, what was detected, and any problems that stop the import."""
    if len(raw) > MAX_IMPORT_BYTES:
        raise ImportProblem(f'The file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB. Split it into smaller files.')
    text, encoding = decode(raw)
    if not text.strip():
        raise ImportProblem('The file is empty.')
    delimiter = delimiter or detect_delimiter(text)
    rows = parse(text, delimiter)
    if not rows:
        raise ImportProblem('The file has no rows.')

    if has_header:
        headers, data = [h.strip() for h in rows[0]], rows[1:]
    else:
        headers, data = [f'Column {i + 1}' for i in range(len(rows[0]))], rows
    problems = []
    if not data:
        problems.append('The file has a header row but no data rows. If the first row is data, untick "First row has column names".')
    if len(data) > MAX_IMPORT_ROWS:
        problems.append(f'The file has {len(data):,} rows. At most {MAX_IMPORT_ROWS:,} can be imported at once: split the file.')
    ragged = [(i + 1, len(r)) for i, r in enumerate(data) if len(r) != len(headers)]
    for number, found in ragged[:MAX_PROBLEMS_SHOWN]:
        problems.append(f'Row {number} has {found} value{"" if found == 1 else "s"} but there are {len(headers)} columns.')
    if len(ragged) > MAX_PROBLEMS_SHOWN:
        problems.append(f'…and {len(ragged) - MAX_PROBLEMS_SHOWN} more rows with the wrong number of values. '
                        'Check the delimiter, or fix the file.')
    return {'headers': headers, 'rows': data, 'delimiter': delimiter, 'encoding': encoding, 'has_header': has_header,
            'problems': problems}


def _normal(name: str) -> str:
    return re.sub(r'[\s\-]+', '_', name.strip().lower())


def suggest_mapping(table_columns: List[str], headers: List[str]) -> Dict[str, Optional[int]]:
    """For each table column, the index of the file column with the same name (ignoring case, spaces and hyphens)."""
    by_name: Dict[str, int] = {}
    for index, header in enumerate(headers):
        by_name.setdefault(_normal(header), index)
    return {column: by_name.get(_normal(column)) for column in table_columns}


def check_mapping(mapping: Any, table_columns: List[str], width: int) -> Dict[str, int]:
    """The mapping reduced to {table column: file column index}, or ImportProblem if it is not usable."""
    if not isinstance(mapping, dict):
        raise ImportProblem('Choose which file column goes into which table column.')
    chosen = {}
    for column, index in mapping.items():
        if index is None or index == '':
            continue
        if column not in table_columns:
            raise ImportProblem(f'The table has no column called "{column}".')
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < width:
            raise ImportProblem(f'"{column}" is mapped to a file column that does not exist.')
        chosen[column] = index
    if not chosen:
        raise ImportProblem('Choose at least one column to import.')
    return chosen


def is_date_type(column_type: Optional[str]) -> bool:
    """A column that holds a date or a date and time (not a time of day, which has no ambiguous order)."""
    t = (column_type or '').lower()
    return 'date' in t or 'timestamp' in t


def normalize_date(value: str) -> Optional[str]:
    """The value with surrounding spaces removed and a 'T' made a space, or None if it is not a real ISO date."""
    text = value.strip()
    match = ISO_DATE.match(text)
    if not match:
        return None
    year, month, day, hour, minute, second = (int(g) if g else 0 for g in match.groups())
    try:
        datetime.date(year, month, day)
    except ValueError:
        return None
    if hour > 23 or minute > 59 or second > 59:
        return None
    return text.replace('T', ' ', 1)


def date_problems(rows: List[List[str]], mapping: Dict[str, int], date_columns) -> List[str]:
    """Messages for values in date columns that are not written like 2026-03-04 or 2026-03-04 10:20:30."""
    found = []
    for number, row in enumerate(rows, start=1):
        for column in date_columns:
            value = row[mapping[column]] if column in mapping else ''
            if value != '' and normalize_date(value) is None:
                found.append(f'Row {number}, "{column}": "{value[:30]}" is not a date written like 2026-03-04 or 2026-03-04 10:20:30. '
                             'Other layouts (04/03/2026) can be read the wrong way round, so they are not accepted.')
    if len(found) > MAX_PROBLEMS_SHOWN:
        more = len(found) - MAX_PROBLEMS_SHOWN
        found = found[:MAX_PROBLEMS_SHOWN] + [f'…and {more} more value{"" if more == 1 else "s"} in the wrong date layout.']
    return found


def build_operations(rows: List[List[str]], mapping: Dict[str, int], empty_as_null: bool, date_columns=()) -> List[Dict[str, Any]]:
    """One insert operation per row. With `empty_as_null`, an empty value is NULL rather than an empty string."""
    operations = []
    for row in rows:
        data = {}
        for column, index in mapping.items():
            value = row[index]
            if column in date_columns and value != '':
                value = normalize_date(value) or value
            data[column] = None if empty_as_null and value == '' else value
        operations.append({'op': 'insert', 'data': data})
    return operations
