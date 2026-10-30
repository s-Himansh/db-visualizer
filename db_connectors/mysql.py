import logging
logger = logging.getLogger(__name__)
import pymysql
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


class MySQLConnector(BaseConnector):
    """MySQL database connector implementation."""

    IDENT_QUOTE = ('`', '`')

    def _prepare(self, database):
        if database:
            self.connection.select_db(database)

    def connect(self) -> bool:
        """Establish connection to MySQL database."""
        try:
            conn_params = {
                'host': self.connection_params.get('host', 'localhost'),
                'port': self.connection_params.get('port', 3306),
                'user': self.connection_params.get('username'),
                'password': self.connection_params.get('password'),
                'database': self.connection_params.get('database'),
                'charset': 'utf8mb4',
                'cursorclass': pymysql.cursors.DictCursor
            }

            # Remove None values
            conn_params = {k: v for k, v in conn_params.items() if v is not None}

            self._conn_params = conn_params
            self.connection = pymysql.connect(**conn_params)
            if self.connection_params.get('read_only'):
                with self.connection.cursor() as cur:
                    cur.execute('SET SESSION TRANSACTION READ ONLY')  # the server refuses writes
            return True
        except Exception as e:
            logger.error(f"MySQL connection error: {e}")
            return False

    def get_relations(self, database: Optional[str] = None) -> List[Dict[str, str]]:
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT table_name AS t, column_name AS c, referenced_table_name AS rt, referenced_column_name AS rc "
            "FROM information_schema.key_column_usage "
            "WHERE table_schema = COALESCE(%s, DATABASE()) AND referenced_table_name IS NOT NULL "
            "ORDER BY table_name, constraint_name, ordinal_position", (database or self.connection_params.get('database'),))
        rows = [{'table': r['t'], 'column': r['c'], 'referenced_table': r['rt'], 'referenced_column': r['rc']}
                for r in cursor.fetchall()]
        cursor.close()
        return rows

    def cancel(self) -> bool:
        # MySQL has no client-side cancel: open a second connection and KILL QUERY the running one
        thread_id = int(self.connection.thread_id())
        killer = pymysql.connect(**self._conn_params)
        try:
            with killer.cursor() as cur:
                cur.execute(f'KILL QUERY {thread_id}')
            return True
        finally:
            killer.close()

    def disconnect(self) -> bool:
        """Close the MySQL connection."""
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
            return True
        except Exception as e:
            logger.error(f"MySQL disconnection error: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """Test the MySQL connection."""
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
        """Get list of all MySQL databases."""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SHOW DATABASES")
            databases = [row['Database'] for row in cursor.fetchall()]
            cursor.close()
            # Filter out system databases
            databases = [db for db in databases if db not in ['information_schema', 'mysql', 'performance_schema', 'sys']]
            return databases
        except Exception as e:
            logger.error(f"Error getting databases: {e}")
            return []

    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get tables and views. Row counts are the catalog's estimates: an exact COUNT(*) per table
        would scan every table in the database each time the list is shown."""
        try:
            if database:
                self.connection.select_db(database)
            schema = database or self.connection_params.get('database')
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT table_name AS name, table_type AS kind, table_rows AS num_rows "
                "FROM information_schema.tables WHERE table_schema = COALESCE(%s, DATABASE()) "
                "ORDER BY table_name", (schema,))
            tables = [{
                'name': row['name'],
                'type': 'view' if 'VIEW' in row['kind'] else 'table',
                'rows': int(row['num_rows']) if row['num_rows'] is not None else None,
                'rows_estimated': True
            } for row in cursor.fetchall()]
            cursor.close()
            return tables
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return []

    def get_columns(self, database: Optional[str] = None, tables: Optional[List[str]] = None) -> Dict[str, List[str]]:
        schema = database or self.connection_params.get('database')
        sql = ("SELECT table_name AS t, column_name AS c FROM information_schema.columns "
               "WHERE table_schema = COALESCE(%s, DATABASE())")
        args = [schema]
        if tables is not None:
            if not tables:
                return {}
            sql += f" AND table_name IN ({', '.join(['%s'] * len(tables))})"
            args += tables
        cursor = self.connection.cursor()
        cursor.execute(sql + " ORDER BY table_name, ordinal_position", args)
        result: Dict[str, List[str]] = {}
        for row in cursor.fetchall():
            result.setdefault(row['t'], []).append(row['c'])
        cursor.close()
        return result

    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """Get the schema of a MySQL table."""
        try:
            if database:
                self.connection.select_db(database)

            cursor = self.connection.cursor()

            # Get column information
            cursor.execute(f"DESCRIBE {self.q(table)}")
            columns = []
            for row in cursor.fetchall():
                columns.append({
                    'name': row['Field'],
                    'type': row['Type'],
                    'nullable': row['Null'] == 'YES',
                    'default': row['Default'],
                    'primary_key': row['Key'] == 'PRI'
                })

            # Get indexes
            cursor.execute(f"SHOW INDEX FROM {self.q(table)}")
            index_dict = {}
            for row in cursor.fetchall():
                idx_name = row['Key_name']
                if idx_name not in index_dict:
                    index_dict[idx_name] = {
                        'name': idx_name,
                        'columns': [],
                        'unique': not row['Non_unique']
                    }
                index_dict[idx_name]['columns'].append(row['Column_name'])

            indexes = list(index_dict.values())

            # Get foreign keys
            cursor.execute(f"""
                SELECT
                    COLUMN_NAME,
                    REFERENCED_TABLE_NAME,
                    REFERENCED_COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = %s
                AND REFERENCED_TABLE_NAME IS NOT NULL
            """, (table,))

            foreign_keys = []
            for row in cursor.fetchall():
                foreign_keys.append({
                    'column': row['COLUMN_NAME'],
                    'referenced_table': row['REFERENCED_TABLE_NAME'],
                    'referenced_column': row['REFERENCED_COLUMN_NAME']
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
        """Execute a SQL query on MySQL database."""
        start_time = time.time()

        try:
            cursor = self.connection.cursor()

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
        """Get paginated data from a MySQL table."""
        try:
            if database:
                self.connection.select_db(database)

            # Build query
            exact, search_cols, term = self.split_search(table, database, filters)
            conditions, filter_values = [], []
            for col, val in exact.items():
                if val is None:
                    conditions.append(f"{self.q(col)} IS NULL")
                else:
                    conditions.append(f"{self.q(col)} = %s")
                    filter_values.append(val)
            if term:
                conditions.append("(" + " OR ".join(f"CAST({self.q(c)} AS CHAR) LIKE %s" for c in search_cols) + ")")
                filter_values += [f'%{term}%'] * len(search_cols)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"SELECT * FROM {self.q(table)}{where}"

            # Add sorting
            if sort_by:
                query += f" ORDER BY {self.q(sort_by)} {sort_order}"

            # Add pagination
            query += f" LIMIT {limit} OFFSET {offset}"

            # Execute query
            cursor = self.connection.cursor()
            cursor.execute(query, filter_values if filter_values else None)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            row_data = list(rows)
            cursor.close()

            # Get total count
            cursor = self.connection.cursor()
            cursor.execute(f"SELECT COUNT(*) as count FROM {self.q(table)}{where}", filter_values if filter_values else None)
            total_count = cursor.fetchone()['count']
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
        """Insert a new row into a MySQL table."""
        try:
            if database:
                self.connection.select_db(database)

            columns = ', '.join([f"{self.q(col)}" for col in data.keys()])
            placeholders = ', '.join(['%s' for _ in data])
            query = f"INSERT INTO {self.q(table)} ({columns}) VALUES ({placeholders})"

            cursor = self.connection.cursor()
            cursor.execute(query, list(data.values()))
            self.connection.commit()
            last_id = cursor.lastrowid
            cursor.close()

            return True, f"Row inserted successfully (ID: {last_id})"
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
        """Update row(s) in a MySQL table."""
        try:
            if database:
                self.connection.select_db(database)

            # Build SET clause
            set_clause = ', '.join([f"{self.q(col)} = %s" for col in data.keys()])

            # Build WHERE clause
            where_clause = ' AND '.join([f"{self.q(col)} = %s" for col in conditions.keys()])

            query = f"UPDATE {self.q(table)} SET {set_clause} WHERE {where_clause}"
            params = list(data.values()) + list(conditions.values())

            cursor = self.connection.cursor()
            cursor.execute(query, params)
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()

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
        """Delete row(s) from a MySQL table."""
        try:
            if database:
                self.connection.select_db(database)

            # Build WHERE clause
            where_clause = ' AND '.join([f"{self.q(col)} = %s" for col in conditions.keys()])

            query = f"DELETE FROM {self.q(table)} WHERE {where_clause}"
            params = list(conditions.values())

            cursor = self.connection.cursor()
            cursor.execute(query, params)
            self.connection.commit()
            rows_affected = cursor.rowcount
            cursor.close()

            return True, f"{rows_affected} row(s) deleted"
        except Exception as e:
            self.connection.rollback()
            return False, f"Delete failed: {str(e)}"
