import contextlib
from abc import ABC, abstractmethod
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


def as_shown(value) -> str:
    """A value as the data grid displays it (and so as it is remembered when a cell is edited).

    The grid reads JSON, so the same conversions apply: NULL is empty, booleans are true/false, and a whole-number
    float has no ".0". The stale-edit check compares these strings, so the two sides must agree exactly.
    """
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    if hasattr(value, 'isoformat'):
        return value.strftime('%Y-%m-%d %H:%M:%S') if hasattr(value, 'hour') else value.strftime('%Y-%m-%d')
    return str(value)


class BaseConnector(ABC):
    """
    Abstract base class for all database connectors.
    Defines the common interface that all database implementations must follow.
    """

    IDENT_QUOTE = ('"', '"')   # how this dialect quotes a table or column name

    @classmethod
    def q(cls, name) -> str:
        """Quote a table/column/schema name for this dialect, doubling any quote character inside it.
        Names reach the connectors from the browser, so they are never pasted into SQL unquoted."""
        name = str(name)
        if not name or '\x00' in name:
            raise ValueError('Invalid table or column name')
        opening, closing = cls.IDENT_QUOTE
        return opening + name.replace(closing, closing * 2) + closing

    SUPPORTS_TRANSACTIONS = True   # False where a batch cannot be rolled back (MongoDB, Redis, Cassandra)
    PLACEHOLDER = '%s'             # how this driver marks a query parameter
    SUPPORTS_PROFILE = True    # column insights use plain SQL aggregates; False for databases that are not SQL
    LIMIT_STYLE = 'limit'      # how this dialect caps a query: 'limit' | 'top' | 'fetch'
    BUCKET_EXPR = 'FLOOR({x})' # whole-number part of an expression, for histogram buckets
    NUMERIC_TYPE = re.compile(r'int|numeric|decimal|number|float|double|real|money|serial', re.I)

    MAX_ROWS = 10_000          # most rows a query result may carry to the UI
    PING_SQL = 'SELECT 1'      # cheapest statement that proves a SQL connection is alive

    def __init__(self, connection_params: Dict[str, Any]):
        """
        Initialize the connector with connection parameters.

        Args:
            connection_params: Dictionary containing connection details
                              (host, port, username, password, database, etc.)
        """
        self.connection_params = connection_params
        self.connection = None
        self.db_type = connection_params.get('type', 'unknown')

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish a connection to the database.

        Returns:
            bool: True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """
        Close the database connection.

        Returns:
            bool: True if disconnection successful, False otherwise
        """
        pass

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        """
        Test the database connection without maintaining it.

        Returns:
            Tuple[bool, str]: (Success status, Message or error description)
        """
        pass

    @abstractmethod
    def get_databases(self) -> List[str]:
        """
        Get list of all databases/schemas available.

        Returns:
            List[str]: List of database names
        """
        pass

    @abstractmethod
    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get list of all tables/collections in the specified database.

        Args:
            database: Database name (if None, use current/default database)

        Returns:
            List[Dict]: List of table information dictionaries with keys:
                       - name: table name
                       - type: table type (table, view, etc.)
                       - rows: estimated row count (optional)
        """
        pass

    @abstractmethod
    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the schema/structure of a specific table.

        Args:
            table: Table/collection name
            database: Database name (if None, use current/default)

        Returns:
            Dict containing:
                - columns: List of column definitions
                - indexes: List of indexes
                - constraints: List of constraints
                - foreign_keys: List of foreign keys
        """
        pass

    @abstractmethod
    def execute_query(self, query: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute a SQL/NoSQL query.

        Args:
            query: Query string
            params: Optional parameters for parameterized queries

        Returns:
            Dict containing:
                - columns: List of column names
                - rows: List of row data
                - row_count: Number of rows affected/returned
                - execution_time: Query execution time in seconds
                - error: Error message if query failed
        """
        pass

    def split_search(self, table: str, database: Optional[str], filters: Optional[Dict]):
        """Split filters into (exact filters, columns to search, search term).

        With no search_column the schema supplies every column, as PostgreSQL does.
        """
        exact = dict(filters or {})
        term = exact.pop('search_term', None)
        column = exact.pop('search_column', None)
        if not term:
            return exact, [], None
        cols = [column] if column else [c['name'] for c in self.get_schema(table, database)['columns']]
        return exact, cols, term

    @abstractmethod
    def get_table_data(
        self,
        table: str,
        database: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
        filters: Optional[Dict] = None,
        sort_by: Optional[str] = None,
        sort_order: str = 'ASC'
    ) -> Dict[str, Any]:
        """
        Get paginated data from a table.

        Args:
            table: Table/collection name
            database: Database name
            limit: Maximum number of rows to return
            offset: Number of rows to skip
            filters: Dictionary of column filters
            sort_by: Column to sort by
            sort_order: 'ASC' or 'DESC'

        Returns:
            Dict containing:
                - columns: List of column names
                - rows: List of row data
                - total_count: Total number of rows (without limit)
                - has_more: Boolean indicating if more rows exist
        """
        pass

    @abstractmethod
    def insert_row(
        self,
        table: str,
        data: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Insert a new row into a table.

        Args:
            table: Table/collection name
            data: Dictionary of column names to values
            database: Database name

        Returns:
            Tuple[bool, str]: (Success status, Error message or success message)
        """
        pass

    @abstractmethod
    def update_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        data: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Update existing row(s) in a table.

        Args:
            table: Table/collection name
            conditions: Dictionary of conditions to identify rows (WHERE clause)
            data: Dictionary of column names to new values
            database: Database name

        Returns:
            Tuple[bool, str]: (Success status, Error message or rows affected message)
        """
        pass

    @abstractmethod
    def delete_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Delete row(s) from a table.

        Args:
            table: Table/collection name
            conditions: Dictionary of conditions to identify rows (WHERE clause)
            database: Database name

        Returns:
            Tuple[bool, str]: (Success status, Error message or rows deleted message)
        """
        pass

    def get_columns(self, database: Optional[str] = None, tables: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """Column names per table, for autocomplete. `tables` limits it to those tables.

        This default asks for each table's schema in turn, which is fine for a handful of tables. The SQL
        connectors override it with a single catalog query, so a big schema costs one round-trip.
        """
        names = tables if tables is not None else [t['name'] for t in self.get_tables(database)][:50]
        result = {}
        for name in names:
            try:
                result[name] = [c['name'] for c in self.get_schema(name, database)['columns']]
            except Exception:
                result[name] = []
        return result

    def get_relations(self, database: Optional[str] = None) -> List[Dict[str, str]]:
        """Every foreign key in the database as {table, column, referenced_table, referenced_column}.

        This default reads each table's schema in turn (capped). The SQL connectors override it with a single
        catalog query so the schema map and link-following stay cheap on big databases.
        """
        relations = []
        for t in self.get_tables(database)[:300]:
            try:
                fks = self.get_schema(t['name'], database).get('foreign_keys', [])
            except Exception:
                continue
            relations += [{'table': t['name'], 'column': fk['column'],
                           'referenced_table': fk['referenced_table'], 'referenced_column': fk['referenced_column']}
                          for fk in fks]
        return relations

    # ---- safe writes ---------------------------------------------------------------------------------------

    last_rowcount: Optional[int] = None   # rows the most recent insert/update/delete touched
    last_conflict: bool = False           # the most recent guarded update found the row changed under it
    _batch = False

    def _ph(self, index: int) -> str:
        return self.PLACEHOLDER

    def _where(self, conditions: Dict[str, Any], first_index: int = 0):
        """WHERE text and its parameters. A NULL condition has to be IS NULL: `col = NULL` never matches anything."""
        parts, params = [], []
        for col, val in conditions.items():
            if val is None:
                parts.append(f'{self.q(col)} IS NULL')
            else:
                parts.append(f'{self.q(col)} = {self._ph(first_index + len(params))}')
                params.append(val)
        return ' AND '.join(parts), params

    def _commit(self):
        if not self._batch:      # inside a batch the batch commits once, at the end
            self.connection.commit()

    def _rollback(self):
        if not self._batch:
            self.connection.rollback()

    def _begin_tx(self):
        """Start a transaction. Drivers that run in autocommit mode switch it off here."""

    def _end_tx(self, commit: bool):
        (self.connection.commit if commit else self.connection.rollback)()

    def _lock_rows(self, table: str, conditions: Dict[str, Any], database: Optional[str]):
        """Lock the rows about to be checked and changed, so nobody can change them in between."""

    def _current_rows(self, table, conditions, database) -> List[dict]:
        """The rows that match `conditions` right now, as the grid would show them."""
        return self.get_table_data(table, database, limit=2, filters=dict(conditions))['rows']

    def _find_conflicts(self, table, operations, database) -> List[dict]:
        """Rows whose edited cells no longer hold what the user saw: someone else changed them (or deleted the row)."""
        conflicts = []
        self._snapshots = {}
        for i, op in enumerate(operations):
            expected = op.get('expected')
            if op.get('op') != 'update' or not expected or not op.get('conditions'):
                continue
            self._lock_rows(table, op['conditions'], database)
            rows = self._current_rows(table, op['conditions'], database)
            if rows:
                self._snapshots[i] = rows[0]
            if not rows:
                conflicts += [{'index': i, 'column': c, 'expected': e, 'actual': None} for c, e in expected.items()][:1]
                continue
            for column, was in expected.items():
                now = as_shown(rows[0].get(column))
                if now != ('' if was is None else str(was)):
                    conflicts.append({'index': i, 'column': column, 'expected': was, 'actual': now})
        return conflicts

    def _apply_op(self, table, op, database, index=None):
        kind = op.get('op')
        self.last_rowcount = None
        self.last_conflict = False
        if kind == 'insert':
            return self.insert_row(table, op.get('data') or {}, database)
        if kind in ('update', 'delete') and not op.get('conditions'):
            return False, 'Refusing to change every row in the table: no row was identified.'
        if kind == 'update':
            snapshot = getattr(self, '_snapshots', {}).get(index) if not self.SUPPORTS_TRANSACTIONS and op.get('expected') else None
            if snapshot is not None:       # no row locks here: the write itself must say "only if it is still what the user saw"
                guard = {c: snapshot.raw.get(c) if hasattr(snapshot, 'raw') else snapshot.get(c) for c in op['expected']}
                return self.update_row(table, op['conditions'], op.get('data') or {}, database, only_if=guard)
            return self.update_row(table, op['conditions'], op.get('data') or {}, database)
        if kind == 'delete':
            ok, msg = self.delete_row(table, op['conditions'], database)
            return (True, 'Row was already gone') if not ok and self.last_rowcount == 0 else (ok, msg)
        return False, f'Unknown operation: {kind!r}'

    def apply_batch(self, table: str, operations: List[dict], database: Optional[str] = None, force: bool = False,
                    dry_run: bool = False) -> Dict[str, Any]:
        """Apply inserts, updates and deletes as one unit.

        With a transactional database it is all or nothing: the edited rows are locked and checked first (every stale
        row is reported at once), then everything is applied and committed together, or rolled back if anything fails.
        Otherwise the operations run in order and the result says exactly how many were applied before a failure.
        `force=True` skips the stale-row check. `dry_run=True` applies everything and then rolls it back, to find out
        whether it would work (transactional databases only).
        """
        if not operations:
            return {'success': True, 'applied': 0, 'results': []}

        if dry_run and not self.SUPPORTS_TRANSACTIONS:
            return {'success': False, 'rolled_back': False, 'applied': 0, 'error': 'A check without saving needs a database that can roll back.'}
        if not self.SUPPORTS_TRANSACTIONS:
            # nothing to roll back, but a row someone else changed is still reported before anything is written
            conflicts = [] if force else self._find_conflicts(table, operations, database)
            if conflicts:
                return {'success': False, 'rolled_back': True, 'conflicts': conflicts,
                        'error': 'Some rows were changed by someone else since you loaded them. Nothing was saved.'}
            results = []
            for i, op in enumerate(operations):
                ok, msg = self._apply_op(table, op, database, i)
                if not ok and self.last_conflict:     # someone changed the row between the check and the write
                    again = self._find_conflicts(table, [op], database)
                    conflicts = [{**c, 'index': i} for c in again] or [{'index': i, 'column': next(iter(op['expected'])), 'expected': None, 'actual': None}]
                    return {'success': False, 'rolled_back': False, 'applied': i, 'conflicts': conflicts,
                            'error': 'A row was changed by someone else while saving.' + (f' {i} earlier change(s) were saved.' if i else ' Nothing was saved.')}
                if not ok:
                    return {'success': False, 'failed_at': i, 'error': msg, 'rolled_back': False, 'applied': i, 'results': results}
                results.append(msg)
            return {'success': True, 'applied': len(operations), 'results': results}

        self._batch = True
        started = False
        try:
            self._prepare(database)
            self._begin_tx()
            started = True
            if not force:
                conflicts = self._find_conflicts(table, operations, database)
                if conflicts:
                    self._end_tx(False)
                    return {'success': False, 'rolled_back': True, 'conflicts': conflicts,
                            'error': 'Some rows were changed by someone else since you loaded them. Nothing was saved.'}
            results = []
            for i, op in enumerate(operations):
                ok, msg = self._apply_op(table, op, database)
                if not ok:
                    self._end_tx(False)
                    return {'success': False, 'failed_at': i, 'error': msg, 'rolled_back': True, 'applied': 0}
                results.append(msg)
            self._end_tx(not dry_run)
            return {'success': True, 'applied': len(operations), 'results': results, 'dry_run': dry_run}
        except Exception as e:
            if started:
                try:
                    self._end_tx(False)
                except Exception:
                    pass
            return {'success': False, 'error': str(e), 'rolled_back': True, 'applied': 0}
        finally:
            self._batch = False

    def check_reference(self, child: str, child_column: str, parent: str, parent_column: str,
                        database: Optional[str] = None, sample: int = 2000) -> Dict[str, int]:
        """How many of the distinct values in the first `sample` non-empty rows of child.column exist in parent.column.
        Returns {'distinct': n, 'matched': m}. Used to test whether a relationship that is not declared really holds."""
        self._prepare(database)
        c, p = self.q(child_column), self.q(parent_column)
        first_rows = self._capped(f'{c} AS v', f'{self.table_ref(child, database)} WHERE {c} IS NOT NULL', int(sample))
        distinct, matched = self._fetch(
            f'SELECT COUNT(*), COUNT(par.{p}) FROM (SELECT DISTINCT v FROM ({first_rows}) s) c '
            f'LEFT JOIN {self.table_ref(parent, database)} par ON par.{p} = c.v')[0]
        return {'distinct': int(distinct), 'matched': int(matched)}

    def orphan_rows(self, child: str, child_column: str, parent: str, parent_column: str,
                    database: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """The rows of child whose child_column holds a value that does not exist in parent.parent_column, and how many there are.
        shortcut: one pass over the child table with no sample, so a very large unindexed table is slow; add a cap if that bites."""
        self._prepare(database)
        c, p = self.q(child_column), self.q(parent_column)
        source = (f'{self.table_ref(child, database)} c LEFT JOIN {self.table_ref(parent, database)} par ON par.{p} = c.{c} '
                  f'WHERE c.{c} IS NOT NULL AND par.{p} IS NULL')
        total = int(self._fetch(f'SELECT COUNT(*) FROM {source}')[0][0])
        shown = self.execute_query(self._capped('c.*', source, int(limit)))
        return {'columns': shown['columns'], 'rows': shown['rows'], 'total_count': total}

    def import_session(self):
        """A context manager around a CSV import. The default does nothing; Oracle uses it to accept ISO dates."""
        return contextlib.nullcontext()

    # ---- column insights -------------------------------------------------------------------------------

    def _prepare(self, database: Optional[str]):
        """Point the session at `database` before profiling, for dialects where that is a session setting."""

    def table_ref(self, table: str, database: Optional[str]) -> str:
        return self.q(table)

    def _capped(self, column: str, source: str, n: int) -> str:
        if self.LIMIT_STYLE == 'top':
            return f'SELECT TOP {n} {column} FROM {source}'
        if self.LIMIT_STYLE == 'fetch':
            return f'SELECT {column} FROM {source} FETCH FIRST {n} ROWS ONLY'
        return f'SELECT {column} FROM {source} LIMIT {n}'

    def _fetch(self, sql: str) -> List[tuple]:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql)
            return [tuple(r.values()) if isinstance(r, dict) else tuple(r) for r in cursor.fetchall()]
        finally:
            cursor.close()

    @staticmethod
    def _plain(value):
        """A value the browser can show: no Decimals or dates, and long text cut short."""
        if value is None:
            return None
        if isinstance(value, Decimal):
            value = float(value)
        if isinstance(value, (int, float, bool)):
            return value
        text = value.isoformat(sep=' ') if hasattr(value, 'isoformat') else str(value)
        return text if len(text) <= 120 else text[:117] + '...'

    def profile_column(self, table: str, column: str, database: Optional[str] = None,
                       sample: Optional[int] = None) -> Dict[str, Any]:
        """What is in a column: counts, nulls, distinct values, range, most common values and (for numbers) a histogram.

        `sample` limits the work to the first N rows, for tables too big to scan; the result says so.
        """
        if not self.SUPPORTS_PROFILE:
            raise NotImplementedError('Column insights are not available for this kind of database.')
        self._prepare(database)
        col = self.q(column)
        ref = self.table_ref(table, database)
        src = f'({self._capped(col, ref, int(sample))}) s' if sample else ref

        info = next((c for c in self.get_schema(table, database)['columns'] if c['name'] == column), {})
        out = {'column': column, 'type': info.get('type'), 'sampled': bool(sample), 'sample_rows': sample or None}

        try:
            total, non_null, distinct, low, high = self._fetch(
                f'SELECT COUNT(*), COUNT({col}), COUNT(DISTINCT {col}), MIN({col}), MAX({col}) FROM {src}')[0]
        except Exception:  # types that cannot be compared or de-duplicated (JSON, binary): counts still work
            total, non_null = self._fetch(f'SELECT COUNT(*), COUNT({col}) FROM {src}')[0]
            distinct = low = high = None
        out.update(total=int(total), non_null=int(non_null), nulls=int(total) - int(non_null),
                   distinct=None if distinct is None else int(distinct), min=self._plain(low), max=self._plain(high))

        try:
            out['top'] = [{'value': self._plain(v), 'count': int(n)} for v, n in self._fetch(
                self._capped_groups(col, src))]
        except Exception:
            out['top'] = []

        numeric = bool(self.NUMERIC_TYPE.search(str(info.get('type') or '')))
        if numeric and non_null:
            try:
                out['avg'] = self._plain(self._fetch(f'SELECT AVG({col} * 1.0) FROM {src}')[0][0])
                lo, hi = float(low), float(high)
                if hi > lo:
                    width = (hi - lo) / 10
                    bucket = self.BUCKET_EXPR.format(x=f'(({col} - {lo!r}) / {width!r})')
                    counts = {}
                    for b, n in self._fetch(f'SELECT {bucket}, COUNT(*) FROM {src} WHERE {col} IS NOT NULL GROUP BY {bucket}'):
                        counts[min(int(b), 9)] = counts.get(min(int(b), 9), 0) + int(n)   # the maximum falls in the last bucket
                    out['histogram'] = [{'from': lo + i * width, 'to': lo + (i + 1) * width, 'count': counts.get(i, 0)} for i in range(10)]
            except Exception:
                pass
        return out

    def _capped_groups(self, col: str, src: str, n: int = 8) -> str:
        """The `n` most common non-null values with their counts."""
        inner = f'SELECT {col} AS v, COUNT(*) AS n FROM {src} WHERE {col} IS NOT NULL GROUP BY {col}'
        if self.LIMIT_STYLE == 'top':
            return f'SELECT TOP {n} v, n FROM ({inner}) g ORDER BY n DESC'
        if self.LIMIT_STYLE == 'fetch':
            return f'SELECT v, n FROM ({inner}) g ORDER BY n DESC FETCH FIRST {n} ROWS ONLY'
        return f'SELECT v, n FROM ({inner}) g ORDER BY n DESC LIMIT {n}'

    def ping(self) -> bool:
        """A real round-trip to the server (is_connected only says an object exists). Drivers without
        cursors override this."""
        try:
            if self.connection is None:
                return False
            cursor = self.connection.cursor()
            cursor.execute(self.PING_SQL)
            cursor.fetchall()
            cursor.close()
            return True
        except Exception:
            return False

    def cancel(self) -> bool:
        """Stop the query currently running on this connection, from another thread.
        Returns False when the driver has no way to do that (the default)."""
        return False

    def is_connected(self) -> bool:
        """
        Check if currently connected to database.

        Returns:
            bool: True if connected, False otherwise
        """
        return self.connection is not None

    def get_connection_info(self) -> Dict[str, Any]:
        """
        Get connection information (without sensitive data).

        Returns:
            Dict with connection details
        """
        info = {
            'type': self.db_type,
            'host': self.connection_params.get('host', 'localhost'),
            'port': self.connection_params.get('port'),
            'database': self.connection_params.get('database'),
            'username': self.connection_params.get('username'),
            'connected': self.is_connected()
        }
        return info
