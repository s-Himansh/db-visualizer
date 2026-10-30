import logging
logger = logging.getLogger(__name__)
import psycopg2
import psycopg2.extras
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple
from .base import BaseConnector


def serialize_value(value):
    """Convert Python objects to JSON-serializable format, preserving raw timestamp format."""
    if value is None:
        return None  # Keep NULL as None, not empty string
    elif isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(value, date):
        return value.strftime('%Y-%m-%d')
    return value


class PostgreSQLConnector(BaseConnector):
    """PostgreSQL database connector implementation."""

    def connect(self) -> bool:
        """Establish connection to PostgreSQL database."""
        try:
            conn_params = {
                'host': self.connection_params.get('host', 'localhost'),
                'port': self.connection_params.get('port', 5432),
                'user': self.connection_params.get('username'),
                'password': self.connection_params.get('password'),
                'database': self.connection_params.get('database', 'postgres')
            }

            # Remove None values
            conn_params = {k: v for k, v in conn_params.items() if v is not None}

            self.connection = psycopg2.connect(**conn_params)
            # Each statement is its own transaction. With autocommit off, one failed statement left the
            # session aborted ("current transaction is aborted") for every later query, and each SELECT
            # left it idle in transaction, holding locks on the server.
            self.connection.autocommit = True
            if self.connection_params.get('read_only'):
                self.connection.readonly = True  # server refuses writes even if the query guard is bypassed
            return True
        except Exception as e:
            logger.error(f"PostgreSQL connection error: {e}")
            return False

    def get_relations(self, database: Optional[str] = None) -> List[Dict[str, str]]:
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT cl.relname, a.attname, fcl.relname, fa.attname
            FROM pg_constraint c
            JOIN pg_class cl ON cl.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = cl.relnamespace
            JOIN pg_class fcl ON fcl.oid = c.confrelid
            CROSS JOIN LATERAL unnest(c.conkey, c.confkey) AS k(attnum, fattnum)
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
            JOIN pg_attribute fa ON fa.attrelid = c.confrelid AND fa.attnum = k.fattnum
            WHERE c.contype = 'f' AND n.nspname = 'public'
            ORDER BY cl.relname, c.conname
        """)
        rows = [{'table': r[0], 'column': r[1], 'referenced_table': r[2], 'referenced_column': r[3]}
                for r in cursor.fetchall()]
        cursor.close()
        return rows

    def cancel(self) -> bool:
        self.connection.cancel()  # psycopg2: safe to call from another thread
        return True

    def disconnect(self) -> bool:
        """Close the PostgreSQL connection."""
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
            return True
        except Exception as e:
            logger.error(f"PostgreSQL disconnection error: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """Test the PostgreSQL connection."""
        try:
            if self.connect():
                cursor = self.connection.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                self.disconnect()
                return True, "Connection successful"
            return False, "Failed to connect"
        except Exception as e:
            self.disconnect()
            return False, f"Connection test failed: {str(e)}"

    def get_databases(self) -> List[str]:
        """Get list of all PostgreSQL databases."""
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT datname FROM pg_database
                WHERE datistemplate = false
                ORDER BY datname
            """)
            databases = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return databases
        except Exception as e:
            logger.error(f"Error getting databases: {e}")
            return []

    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all tables and views in the current database."""
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT
                    t.table_name,
                    t.table_type,
                    COALESCE(
                        (SELECT c.reltuples::bigint
                         FROM pg_class c
                         JOIN pg_namespace n ON n.oid = c.relnamespace
                         WHERE c.relname = t.table_name
                         AND n.nspname = 'public'
                         AND c.reltuples >= 0),
                        NULL
                    ) as row_count
                FROM information_schema.tables t
                WHERE t.table_schema = 'public'
                ORDER BY t.table_name
            """)

            tables = []
            for row in cursor.fetchall():
                row_count = row[2]
                # Filter out -1 and negative values
                if row_count is not None and row_count < 0:
                    row_count = None

                tables.append({
                    'name': row[0],
                    'type': 'view' if row[1] == 'VIEW' else 'table',
                    'rows': row_count,
                    'rows_estimated': True
                })

            cursor.close()
            return tables
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return []

    def get_columns(self, database: Optional[str] = None, tables: Optional[List[str]] = None) -> Dict[str, List[str]]:
        sql = "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"
        args: list = []
        if tables is not None:
            if not tables:
                return {}
            sql += " AND table_name = ANY(%s)"
            args.append(tables)
        cursor = self.connection.cursor()
        cursor.execute(sql + " ORDER BY table_name, ordinal_position", args or None)
        result: Dict[str, List[str]] = {}
        for table, column in cursor.fetchall():
            result.setdefault(table, []).append(column)
        cursor.close()
        return result

    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """Get the schema of a PostgreSQL table."""
        try:
            cursor = self.connection.cursor()

            # Get column information
            cursor.execute("""
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_name = %s
                AND table_schema = 'public'
                ORDER BY ordinal_position
            """, (table,))

            columns = []
            for row in cursor.fetchall():
                columns.append({
                    'name': row[0],
                    'type': row[1],
                    'nullable': row[2] == 'YES',
                    'default': row[3],
                    'primary_key': False  # Will be updated below
                })

            # Get primary keys
            cursor.execute("""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = %s::regclass
                AND i.indisprimary
            """, (table,))

            pk_columns = {row[0] for row in cursor.fetchall()}
            for col in columns:
                if col['name'] in pk_columns:
                    col['primary_key'] = True

            # Get indexes
            cursor.execute("""
                SELECT
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE tablename = %s
                AND schemaname = 'public'
            """, (table,))

            indexes = []
            for row in cursor.fetchall():
                indexes.append({
                    'name': row[0],
                    'definition': row[1]
                })

            # Get foreign keys
            cursor.execute("""
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = %s
            """, (table,))

            foreign_keys = []
            for row in cursor.fetchall():
                foreign_keys.append({
                    'column': row[0],
                    'referenced_table': row[1],
                    'referenced_column': row[2]
                })

            cursor.close()

            return {
                'columns': columns,
                'indexes': indexes,
                'constraints': [],
                'foreign_keys': foreign_keys
            }
        except Exception as e:
            logger.error(f"Error getting schema: {e}")
            return {'columns': [], 'indexes': [], 'constraints': [], 'foreign_keys': []}

    def execute_query(self, query: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute a SQL query on PostgreSQL database."""
        start_time = time.time()

        try:
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Check if this is a SELECT query
            if cursor.description:
                rows = cursor.fetchmany(self.MAX_ROWS + 1)
                columns = [desc[0] for desc in cursor.description]
                # Serialize datetime objects to preserve raw format
                row_data = [{col: serialize_value(row[col]) for col in columns} for row in rows]
                row_count = len(rows)
            else:
                # For INSERT, UPDATE, DELETE
                self.connection.commit()
                row_data = []
                columns = []
                row_count = cursor.rowcount

            execution_time = time.time() - start_time
            cursor.close()

            return {
                'columns': columns,
                'rows': row_data,
                'row_count': row_count,
                'execution_time': execution_time,
                'error': None
            }
        except Exception as e:
            self.connection.rollback()
            execution_time = time.time() - start_time
            return {
                'columns': [],
                'rows': [],
                'row_count': 0,
                'execution_time': execution_time,
                'error': str(e)
            }

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
        """Get paginated data from a PostgreSQL table with search support."""
        try:
            # Build query
            query = f'SELECT * FROM {self.q(table)}'
            filter_values = []

            # Add filters
            conditions = []
            if filters:
                # Handle search filters separately
                if 'search_term' in filters and filters['search_term']:
                    search_term = filters['search_term']
                    search_column = filters.get('search_column')

                    if search_column:
                        # Search specific column with LIKE
                        conditions.append(f'{self.q(search_column)}::text ILIKE %s')
                        filter_values.append(f'%{search_term}%')
                    else:
                        # Search all columns - get column names first
                        cursor = self.connection.cursor()
                        cursor.execute(f"""
                            SELECT column_name FROM information_schema.columns
                            WHERE table_name = %s
                        """, (table,))
                        all_columns = [row[0] for row in cursor.fetchall()]
                        cursor.close()

                        # Build OR condition for all columns
                        col_conditions = []
                        for col in all_columns:
                            col_conditions.append(f'{self.q(col)}::text ILIKE %s')
                            filter_values.append(f'%{search_term}%')
                        if col_conditions:
                            conditions.append(f"({' OR '.join(col_conditions)})")

                # Handle other filters (exact match)
                for col, val in filters.items():
                    if col not in ['search_term', 'search_column']:
                        if val is None:
                            conditions.append(f'{self.q(col)} IS NULL')
                        else:
                            conditions.append(f'{self.q(col)} = %s')
                            filter_values.append(val)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Add sorting
            if sort_by:
                query += f' ORDER BY {self.q(sort_by)} {sort_order}'

            # Add pagination
            query += f" LIMIT {limit} OFFSET {offset}"

            # Execute query
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(query, filter_values if filter_values else None)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            row_data = [dict(row) for row in rows]
            cursor.close()

            # Get total count with same filters
            count_query = f'SELECT COUNT(*) FROM {self.q(table)}'
            if conditions:
                count_query += " WHERE " + " AND ".join(conditions)

            cursor = self.connection.cursor()
            cursor.execute(count_query, filter_values if filter_values else None)
            total_count = cursor.fetchone()[0]
            cursor.close()

            return {
                'columns': columns,
                'rows': row_data,
                'total_count': total_count,
                'has_more': (offset + limit) < total_count
            }
        except Exception as e:
            logger.error(f"Error getting table data: {e}")
            raise

    def insert_row(
        self,
        table: str,
        data: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Insert a new row into a PostgreSQL table."""
        try:
            cursor = self.connection.cursor()

            # Get column types to handle JSONB properly
            cursor.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = %s
            """, (table,))
            column_types = {row[0]: row[1] for row in cursor.fetchall()}

            # Build column list and placeholders - use actual column type (json vs jsonb)
            columns = ', '.join([f'{self.q(col)}' for col in data.keys()])
            placeholders = []
            for col in data.keys():
                col_type = column_types.get(col, '').lower()
                if col_type in ('json', 'jsonb'):
                    placeholders.append(f'%s::{col_type}')
                else:
                    placeholders.append('%s')
            placeholders_str = ', '.join(placeholders)

            query = f'INSERT INTO {self.q(table)} ({columns}) VALUES ({placeholders_str})'

            cursor.execute(query, list(data.values()))
            self.connection.commit()
            cursor.close()

            return True, "Row inserted successfully"
        except Exception as e:
            self.connection.rollback()
            return False, f"Insert failed: {str(e)}"

    def update_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        data: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Update row(s) in a PostgreSQL table."""
        try:
            cursor = self.connection.cursor()

            # Get column types
            cursor.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = %s
            """, (table,))
            column_types = {row[0]: row[1] for row in cursor.fetchall()}

            # Get primary key columns - more robust query
            cursor.execute("""
                SELECT c.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage AS ccu USING (constraint_schema, constraint_name)
                JOIN information_schema.columns AS c ON c.table_schema = tc.constraint_schema
                    AND tc.table_name = c.table_name AND ccu.column_name = c.column_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_name = %s
            """, (table,))
            pk_columns = {row[0] for row in cursor.fetchall()}

            # Build SET clause - use actual column type (json vs jsonb)
            set_parts = []
            for col in data.keys():
                col_type = column_types.get(col, '').lower()
                if col_type in ('json', 'jsonb'):
                    set_parts.append(f'{self.q(col)} = %s::{col_type}')
                else:
                    set_parts.append(f'{self.q(col)} = %s')
            set_clause = ', '.join(set_parts)

            # Build WHERE clause - prioritize primary keys
            where_parts = []
            where_params = []

            # If we have primary key columns in conditions, use ONLY those
            pk_conditions = {col: val for col, val in conditions.items() if col in pk_columns}

            if pk_conditions:
                # Use only primary keys for WHERE clause
                for col, value in pk_conditions.items():
                    if value is None:
                        where_parts.append(f'{self.q(col)} IS NULL')
                    else:
                        where_parts.append(f'{self.q(col)} = %s')
                        where_params.append(value)
            else:
                # No primary keys available, use non-JSON, non-timestamp columns
                for col, value in conditions.items():
                    col_type = column_types.get(col, '').lower()
                    # Skip JSON/JSONB columns
                    if col_type in ('json', 'jsonb'):
                        continue
                    # Skip timestamp columns
                    if 'timestamp' in col_type or col_type == 'date':
                        continue
                    if value is None:
                        where_parts.append(f'{self.q(col)} IS NULL')
                    else:
                        where_parts.append(f'{self.q(col)} = %s')
                        where_params.append(value)

            # Safety check
            if not where_parts:
                return False, "Update failed: No valid columns for WHERE clause. Table needs a primary key or non-JSON/timestamp columns."

            where_clause = ' AND '.join(where_parts)
            query = f'UPDATE {self.q(table)} SET {set_clause} WHERE {where_clause}'
            params = list(data.values()) + where_params


            cursor.execute(query, params)
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()

            if rows_affected == 0:
                return False, "Update failed: No rows matched the WHERE conditions. Data may have changed."

            return True, f"{rows_affected} row(s) updated"
        except Exception as e:
            self.connection.rollback()
            return False, f"Update failed: {str(e)}"

    def delete_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Delete row(s) from a PostgreSQL table."""
        try:
            cursor = self.connection.cursor()

            # Get column types
            cursor.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = %s
            """, (table,))
            column_types = {row[0]: row[1] for row in cursor.fetchall()}

            # Get primary key columns - more robust query
            cursor.execute("""
                SELECT c.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage AS ccu USING (constraint_schema, constraint_name)
                JOIN information_schema.columns AS c ON c.table_schema = tc.constraint_schema
                    AND tc.table_name = c.table_name AND ccu.column_name = c.column_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_name = %s
            """, (table,))
            pk_columns = {row[0] for row in cursor.fetchall()}

            # Build WHERE clause - prioritize primary keys
            where_parts = []
            where_params = []

            # If we have primary key columns in conditions, use ONLY those
            pk_conditions = {col: val for col, val in conditions.items() if col in pk_columns}

            if pk_conditions:
                # Use only primary keys for WHERE clause
                for col, value in pk_conditions.items():
                    if value is None:
                        where_parts.append(f'{self.q(col)} IS NULL')
                    else:
                        where_parts.append(f'{self.q(col)} = %s')
                        where_params.append(value)
            else:
                # No primary keys available, use non-JSON, non-timestamp columns
                for col, value in conditions.items():
                    col_type = column_types.get(col, '').lower()
                    # Skip JSON/JSONB columns
                    if col_type in ('json', 'jsonb'):
                        continue
                    # Skip timestamp columns
                    if 'timestamp' in col_type or col_type == 'date':
                        continue
                    if value is None:
                        where_parts.append(f'{self.q(col)} IS NULL')
                    else:
                        where_parts.append(f'{self.q(col)} = %s')
                        where_params.append(value)

            # Safety check
            if not where_parts:
                return False, "Delete failed: No valid columns for WHERE clause. Table needs a primary key or non-JSON/timestamp columns."

            where_clause = ' AND '.join(where_parts)
            query = f'DELETE FROM {self.q(table)} WHERE {where_clause}'
            params = where_params

            cursor.execute(query, params)
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()

            if rows_affected == 0:
                return False, "Delete failed: No rows matched the WHERE conditions. Data may have changed."

            return True, f"{rows_affected} row(s) deleted"
        except Exception as e:
            self.connection.rollback()
            return False, f"Delete failed: {str(e)}"
