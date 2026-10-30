import logging
logger = logging.getLogger(__name__)
import pymssql
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


class SQLServerConnector(BaseConnector):
    """SQL Server database connector implementation."""

    IDENT_QUOTE = ('[', ']')
    LIMIT_STYLE = 'top'

    def _prepare(self, database):
        if database:
            cursor = self.connection.cursor()
            cursor.execute(f"USE {self.q(database)}")
            cursor.close()

    def connect(self) -> bool:
        """Establish connection to SQL Server database."""
        try:
            conn_params = {
                'server': self.connection_params.get('host', 'localhost'),
                'port': self.connection_params.get('port', 1433),
                'user': self.connection_params.get('username'),
                'password': self.connection_params.get('password'),
                'database': self.connection_params.get('database', 'master')
            }

            # Remove None values
            conn_params = {k: v for k, v in conn_params.items() if v is not None}

            # Combine server and port
            if 'port' in conn_params:
                conn_params['server'] = f"{conn_params['server']}:{conn_params['port']}"
                del conn_params['port']

            self.connection = pymssql.connect(**conn_params)
            self.connection.autocommit(False)
            return True
        except Exception as e:
            logger.error(f"SQL Server connection error: {e}")
            return False

    def disconnect(self) -> bool:
        """Close the SQL Server connection."""
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
            return True
        except Exception as e:
            logger.error(f"SQL Server disconnection error: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """Test the SQL Server connection."""
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
        """Get list of all SQL Server databases."""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name")
            databases = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return databases
        except Exception as e:
            logger.error(f"Error getting databases: {e}")
            return []

    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get tables and views. Row counts come from partition statistics, not a COUNT(*) per table."""
        try:
            if database:
                cursor = self.connection.cursor()
                cursor.execute(f"USE {self.q(database)}")
                cursor.close()

            cursor = self.connection.cursor()
            try:
                cursor.execute("""
                    SELECT t.TABLE_NAME, t.TABLE_TYPE, p.n
                    FROM INFORMATION_SCHEMA.TABLES t
                    LEFT JOIN (
                        SELECT object_id, SUM(row_count) AS n FROM sys.dm_db_partition_stats
                        WHERE index_id IN (0, 1) GROUP BY object_id
                    ) p ON p.object_id = OBJECT_ID(QUOTENAME(t.TABLE_SCHEMA) + '.' + QUOTENAME(t.TABLE_NAME))
                    WHERE t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                    ORDER BY t.TABLE_NAME
                """)
            except Exception as e:  # e.g. no VIEW DATABASE STATE permission: still list the tables, without counts
                logger.warning(f"Row counts unavailable, listing names only: {e}")
                cursor = self.connection.cursor()
                cursor.execute("SELECT TABLE_NAME, TABLE_TYPE, NULL FROM INFORMATION_SCHEMA.TABLES "
                               "WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW') ORDER BY TABLE_NAME")
            tables = [{
                'name': row[0],
                'type': 'view' if row[1] == 'VIEW' else 'table',
                'rows': int(row[2]) if row[2] is not None and row[1] != 'VIEW' else None,
                'rows_estimated': True
            } for row in cursor.fetchall()]
            cursor.close()
            return tables
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return []

    def get_relations(self, database: Optional[str] = None) -> List[Dict[str, str]]:
        try:
            if database:
                cursor = self.connection.cursor()
                cursor.execute(f"USE {self.q(database)}")
                cursor.close()
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT OBJECT_NAME(fkc.parent_object_id), COL_NAME(fkc.parent_object_id, fkc.parent_column_id),
                       OBJECT_NAME(fkc.referenced_object_id), COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id)
                FROM sys.foreign_key_columns fkc
                ORDER BY 1, fkc.constraint_object_id, fkc.constraint_column_id
            """)
            rows = [{'table': r[0], 'column': r[1], 'referenced_table': r[2], 'referenced_column': r[3]}
                    for r in cursor.fetchall()]
            cursor.close()
            return rows
        except Exception as e:
            logger.warning(f"Catalog query for relations failed ({e}); reading table by table")
            return super().get_relations(database)

    def get_columns(self, database: Optional[str] = None, tables: Optional[List[str]] = None) -> Dict[str, List[str]]:
        if database:
            cursor = self.connection.cursor()
            cursor.execute(f"USE {self.q(database)}")
            cursor.close()
        sql = "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS"
        args: list = []
        if tables is not None:
            if not tables:
                return {}
            sql += f" WHERE TABLE_NAME IN ({', '.join(['%s'] * len(tables))})"
            args = list(tables)
        cursor = self.connection.cursor()
        cursor.execute(sql + " ORDER BY TABLE_NAME, ORDINAL_POSITION", tuple(args) if args else None)
        result: Dict[str, List[str]] = {}
        for table, column in cursor.fetchall():
            result.setdefault(table, []).append(column)
        cursor.close()
        return result

    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """Get the schema of a SQL Server table."""
        try:
            if database:
                cursor = self.connection.cursor()
                cursor.execute(f"USE {self.q(database)}")
                cursor.close()

            cursor = self.connection.cursor()

            # Get column information
            cursor.execute("""
                SELECT
                    COLUMN_NAME,
                    DATA_TYPE,
                    IS_NULLABLE,
                    COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
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
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE OBJECTPROPERTY(OBJECT_ID(CONSTRAINT_SCHEMA + '.' + CONSTRAINT_NAME), 'IsPrimaryKey') = 1
                AND TABLE_NAME = %s
            """, (table,))

            pk_columns = {row[0] for row in cursor.fetchall()}
            for col in columns:
                if col['name'] in pk_columns:
                    col['primary_key'] = True

            # Get indexes
            cursor.execute("""
                SELECT
                    i.name AS index_name,
                    COL_NAME(ic.object_id, ic.column_id) AS column_name
                FROM sys.indexes AS i
                INNER JOIN sys.index_columns AS ic
                    ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                WHERE i.object_id = OBJECT_ID(%s)
                ORDER BY i.name, ic.key_ordinal
            """, (table,))

            index_dict = {}
            for row in cursor.fetchall():
                idx_name = row[0]
                if idx_name not in index_dict:
                    index_dict[idx_name] = {
                        'name': idx_name,
                        'columns': []
                    }
                index_dict[idx_name]['columns'].append(row[1])

            indexes = list(index_dict.values())

            # Get foreign keys
            cursor.execute("""
                SELECT
                    COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS column_name,
                    OBJECT_NAME(fkc.referenced_object_id) AS referenced_table,
                    COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS referenced_column
                FROM sys.foreign_key_columns AS fkc
                WHERE fkc.parent_object_id = OBJECT_ID(%s)
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
        """Execute a SQL query on SQL Server database."""
        start_time = time.time()

        try:
            cursor = self.connection.cursor(as_dict=True)

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
        """Get paginated data from a SQL Server table."""
        try:
            if database:
                cursor = self.connection.cursor()
                cursor.execute(f"USE {self.q(database)}")
                cursor.close()

            # Build query with SQL Server pagination (OFFSET/FETCH)
            exact, search_cols, term = self.split_search(table, database, filters)
            conditions, values = [], []
            for col, val in exact.items():
                if val is None:
                    conditions.append(f"{self.q(col)} IS NULL")
                else:
                    conditions.append(f"{self.q(col)} = %s")
                    values.append(val)
            if term:
                conditions.append("(" + " OR ".join(f"CAST({self.q(c)} AS NVARCHAR(MAX)) LIKE %s" for c in search_cols) + ")")
                values += [f'%{term}%'] * len(search_cols)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"SELECT * FROM {self.q(table)}{where}"

            # SQL Server requires ORDER BY for OFFSET/FETCH
            if sort_by:
                query += f" ORDER BY {self.q(sort_by)} {sort_order}"
            else:
                # Use first column if no sort specified
                query += " ORDER BY (SELECT NULL)"

            # Add pagination
            query += f" OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"

            # Execute query
            cursor = self.connection.cursor(as_dict=True)
            cursor.execute(query, tuple(values) if values else None)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            row_data = list(rows)
            cursor.close()

            # Get total count
            cursor = self.connection.cursor()
            cursor.execute(f"SELECT COUNT(*) as count FROM {self.q(table)}{where}", tuple(values) if values else None)
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
        """Insert a new row into a SQL Server table."""
        try:
            if database:
                cursor = self.connection.cursor()
                cursor.execute(f"USE {self.q(database)}")
                cursor.close()

            columns = ', '.join([f"{self.q(col)}" for col in data.keys()])
            placeholders = ', '.join(['%s' for _ in data])
            query = f"INSERT INTO {self.q(table)} ({columns}) VALUES ({placeholders})"

            cursor = self.connection.cursor()
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
        """Update row(s) in a SQL Server table."""
        try:
            if database:
                cursor = self.connection.cursor()
                cursor.execute(f"USE {self.q(database)}")
                cursor.close()

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
        """Delete row(s) from a SQL Server table."""
        try:
            if database:
                cursor = self.connection.cursor()
                cursor.execute(f"USE {self.q(database)}")
                cursor.close()

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
