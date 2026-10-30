import logging
logger = logging.getLogger(__name__)
import os
import sqlite3
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple
from .base import BaseConnector


def serialize_value(value):
    """Convert Python objects to JSON-serializable format, preserving raw timestamp format."""
    if value is None:
        return None  # Keep NULL as None, not empty string
    elif isinstance(value, datetime):
        # Return ISO format without timezone conversion
        return value.strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(value, date):
        return value.strftime('%Y-%m-%d')
    return value


class SQLiteConnector(BaseConnector):
    """SQLite database connector implementation."""

    # Backticks, not double quotes: SQLite treats a double-quoted name that matches no column as a
    # string literal, so a typo or hostile column name would silently match nothing instead of failing.
    IDENT_QUOTE = ('`', '`')
    BUCKET_EXPR = 'CAST({x} AS INTEGER)'   # the FLOOR() math function is an optional SQLite build feature

    def connect(self) -> bool:
        """Establish connection to SQLite database."""
        try:
            db_path = self.connection_params.get('database') or self.connection_params.get('path')
            if not db_path:
                raise ValueError("Database path is required for SQLite connection")

            self.connection = sqlite3.connect(db_path, check_same_thread=False)
            self.connection.row_factory = sqlite3.Row
            if self.connection_params.get('read_only'):
                self.connection.execute('PRAGMA query_only = ON')  # the engine refuses writes
            return True
        except Exception as e:
            logger.error(f"SQLite connection error: {e}")
            return False

    def cancel(self) -> bool:
        self.connection.interrupt()  # sqlite3: safe to call from another thread
        return True

    def disconnect(self) -> bool:
        """Close the SQLite connection."""
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
            return True
        except Exception as e:
            logger.error(f"SQLite disconnection error: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """Test the SQLite connection."""
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
        """
        SQLite has single database per file.
        Returns the current database name.
        """
        db_path = self.connection_params.get('database') or self.connection_params.get('path')
        return [db_path.split('/')[-1] if db_path else 'main']

    # Above this file size an exact COUNT(*) per table is no longer cheap, so counts are skipped
    EXACT_COUNT_MAX_BYTES = 50 * 1024 * 1024

    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get tables and views. SQLite keeps no row-count statistics, so counts are exact but only
        computed for small files."""
        try:
            path = self.connection_params.get('database') or self.connection_params.get('path') or ''
            try:
                small = os.path.getsize(path) <= self.EXACT_COUNT_MAX_BYTES
            except OSError:  # :memory: and the like
                small = True
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT name, type
                FROM sqlite_master
                WHERE type IN ('table', 'view')
                AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
            tables = []
            for row in cursor.fetchall():
                row_count = None
                if row[1] == 'table' and small:
                    try:
                        row_count = self.connection.execute(f'SELECT COUNT(*) FROM {self.q(row[0])}').fetchone()[0]
                    except sqlite3.Error:
                        pass
                tables.append({'name': row[0], 'type': row[1], 'rows': row_count, 'rows_estimated': False})
            cursor.close()
            return tables
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return []

    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """Get the schema of a SQLite table."""
        try:
            cursor = self.connection.cursor()

            # Get column information
            cursor.execute(f"PRAGMA table_info({self.q(table)})")
            columns = []
            for row in cursor.fetchall():
                columns.append({
                    'name': row[1],
                    'type': row[2],
                    'nullable': not row[3],
                    'default': row[4],
                    'primary_key': bool(row[5])
                })

            # Get indexes
            cursor.execute(f"PRAGMA index_list({self.q(table)})")
            indexes = []
            for idx_row in cursor.fetchall():
                idx_name = idx_row[1]
                cursor.execute(f"PRAGMA index_info({self.q(idx_name)})")
                idx_columns = [col[2] for col in cursor.fetchall()]
                indexes.append({
                    'name': idx_name,
                    'columns': idx_columns,
                    'unique': bool(idx_row[2])
                })

            # Get foreign keys
            cursor.execute(f"PRAGMA foreign_key_list({self.q(table)})")
            foreign_keys = []
            for fk_row in cursor.fetchall():
                foreign_keys.append({
                    'column': fk_row[3],
                    'referenced_table': fk_row[2],
                    'referenced_column': fk_row[4]
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
        """Execute a SQL query on SQLite database."""
        start_time = time.time()

        try:
            cursor = self.connection.cursor()

            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Check if this is a SELECT query
            # Statements that return rows have a description (SELECT, but also WITH, PRAGMA, VALUES, EXPLAIN)
            if cursor.description:
                rows = cursor.fetchmany(self.MAX_ROWS + 1)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
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
        """Get paginated data from a SQLite table."""
        try:
            # Build query
            exact, search_cols, term = self.split_search(table, database, filters)
            conditions, values = [], []
            for col, val in exact.items():
                if val is None:
                    conditions.append(f"{self.q(col)} IS NULL")
                else:
                    conditions.append(f"{self.q(col)} = ?")
                    values.append(val)
            if term:
                conditions.append("(" + " OR ".join(f'CAST({self.q(c)} AS TEXT) LIKE ?' for c in search_cols) + ")")
                values += [f'%{term}%'] * len(search_cols)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"SELECT * FROM {self.q(table)}{where}"

            # Add sorting
            if sort_by:
                query += f" ORDER BY {self.q(sort_by)} {sort_order}"

            # Add pagination
            query += f" LIMIT {limit} OFFSET {offset}"

            # Execute query
            result = self.execute_query(query, values)

            # Get total count
            cursor = self.connection.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {self.q(table)}{where}", values)
            total_count = cursor.fetchone()[0]
            cursor.close()

            return {
                'columns': result['columns'],
                'rows': result['rows'],
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
        """Insert a new row into a SQLite table."""
        try:
            columns = ', '.join(self.q(c) for c in data.keys())
            placeholders = ', '.join(['?' for _ in data])
            query = f"INSERT INTO {self.q(table)} ({columns}) VALUES ({placeholders})"

            cursor = self.connection.cursor()
            cursor.execute(query, list(data.values()))
            self.connection.commit()
            cursor.close()

            return True, f"Row inserted successfully (ID: {cursor.lastrowid})"
        except Exception as e:
            return False, f"Insert failed: {str(e)}"

    def update_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        data: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Update row(s) in a SQLite table."""
        try:
            # Build SET clause
            set_clause = ', '.join([f"{self.q(col)} = ?" for col in data.keys()])

            # Build WHERE clause
            where_clause = ' AND '.join([f"{self.q(col)} = ?" for col in conditions.keys()])

            query = f"UPDATE {self.q(table)} SET {set_clause} WHERE {where_clause}"
            params = list(data.values()) + list(conditions.values())

            cursor = self.connection.cursor()
            cursor.execute(query, params)
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()

            return True, f"{rows_affected} row(s) updated"
        except Exception as e:
            return False, f"Update failed: {str(e)}"

    def delete_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Delete row(s) from a SQLite table."""
        try:
            # Build WHERE clause
            where_clause = ' AND '.join([f"{self.q(col)} = ?" for col in conditions.keys()])

            query = f"DELETE FROM {self.q(table)} WHERE {where_clause}"
            params = list(conditions.values())

            cursor = self.connection.cursor()
            cursor.execute(query, params)
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()

            return True, f"{rows_affected} row(s) deleted"
        except Exception as e:
            return False, f"Delete failed: {str(e)}"
