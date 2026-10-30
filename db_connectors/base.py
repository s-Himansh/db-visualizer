from abc import ABC, abstractmethod
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


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
