import logging
logger = logging.getLogger(__name__)
import oracledb  # python-oracledb: 'thin' mode by default, so no Oracle Instant Client install is needed
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


class OracleConnector(BaseConnector):
    """Oracle database connector implementation."""

    def connect(self) -> bool:
        """Establish connection to Oracle database."""
        try:
            host = self.connection_params.get('host', 'localhost')
            port = self.connection_params.get('port', 1521)
            service_name = self.connection_params.get('service_name') or self.connection_params.get('database')
            username = self.connection_params.get('username')
            password = self.connection_params.get('password')

            if not all([host, username, password]):
                raise ValueError("Host, username, and password are required")

            # Build DSN
            if service_name:
                dsn = oracledb.makedsn(host, port, service_name=service_name)
            else:
                dsn = f"{host}:{port}"

            self.connection = oracledb.connect(user=username, password=password, dsn=dsn)
            return True
        except Exception as e:
            logger.error(f"Oracle connection error: {e}")
            return False

    PING_SQL = 'SELECT 1 FROM dual'
    LIMIT_STYLE = 'fetch'
    BUCKET_EXPR = 'TRUNC({x})'

    def table_ref(self, table, database):
        return self.qualified(database, table)

    def qualified(self, schema, table) -> str:
        """Quoted [schema.]table for use in SQL."""
        return f"{self.q(schema)}.{self.q(table)}" if schema else self.q(table)

    def cancel(self) -> bool:
        self.connection.cancel()
        return True

    def disconnect(self) -> bool:
        """Close the Oracle connection."""
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
            return True
        except Exception as e:
            logger.error(f"Oracle disconnection error: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """Test the Oracle connection."""
        try:
            if self.connect():
                cursor = self.connection.cursor()
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.close()
                self.disconnect()
                return True, "Connection successful"
            return False, "Failed to connect"
        except Exception as e:
            self.disconnect()
            return False, f"Connection test failed: {str(e)}"

    def get_databases(self) -> List[str]:
        """
        Oracle doesn't have multiple databases like MySQL/PostgreSQL.
        Returns schemas instead.
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT username
                FROM all_users
                ORDER BY username
            """)
            schemas = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return schemas
        except Exception as e:
            logger.error(f"Error getting schemas: {e}")
            return []

    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all tables and views in the current schema or specified schema."""
        try:
            cursor = self.connection.cursor()

            # Get current schema if not specified
            if not database:
                cursor.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL")
                database = cursor.fetchone()[0]

            cursor.execute("""
                SELECT table_name, 'TABLE' as table_type, num_rows
                FROM all_tables
                WHERE owner = :schema
                UNION ALL
                SELECT view_name, 'VIEW' as table_type, NULL as num_rows
                FROM all_views
                WHERE owner = :schema
                ORDER BY 1
            """, schema=database)

            tables = []
            for row in cursor.fetchall():
                tables.append({
                    'name': row[0],
                    'type': row[1].lower(),
                    'rows': row[2],
                    'rows_estimated': True
                })

            cursor.close()
            return tables
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return []

    def get_relations(self, database: Optional[str] = None) -> List[Dict[str, str]]:
        try:
            cursor = self.connection.cursor()
            if not database:
                cursor.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL")
                database = cursor.fetchone()[0]
            cursor.execute("""
                SELECT a.table_name, a.column_name, c_pk.table_name, b.column_name
                FROM all_cons_columns a
                JOIN all_constraints c ON a.owner = c.owner AND a.constraint_name = c.constraint_name
                JOIN all_constraints c_pk ON c.r_owner = c_pk.owner AND c.r_constraint_name = c_pk.constraint_name
                JOIN all_cons_columns b ON c_pk.owner = b.owner AND c_pk.constraint_name = b.constraint_name
                                       AND b.position = a.position
                WHERE c.constraint_type = 'R' AND a.owner = :schema
                ORDER BY a.table_name, a.constraint_name, a.position
            """, {'schema': database})
            rows = [{'table': r[0], 'column': r[1], 'referenced_table': r[2], 'referenced_column': r[3]}
                    for r in cursor.fetchall()]
            cursor.close()
            return rows
        except Exception as e:
            logger.warning(f"Catalog query for relations failed ({e}); reading table by table")
            return super().get_relations(database)

    def get_columns(self, database: Optional[str] = None, tables: Optional[List[str]] = None) -> Dict[str, List[str]]:
        cursor = self.connection.cursor()
        if not database:
            cursor.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL")
            database = cursor.fetchone()[0]
        sql = "SELECT table_name, column_name FROM all_tab_columns WHERE owner = :schema"
        binds = {'schema': database}
        if tables is not None:
            if not tables:
                return {}
            names = []
            for i, t in enumerate(tables):
                binds[f't{i}'] = t
                names.append(f':t{i}')
            sql += f" AND table_name IN ({', '.join(names)})"
        cursor.execute(sql + " ORDER BY table_name, column_id", binds)
        result: Dict[str, List[str]] = {}
        for table, column in cursor.fetchall():
            result.setdefault(table, []).append(column)
        cursor.close()
        return result

    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """Get the schema of an Oracle table."""
        try:
            cursor = self.connection.cursor()

            # Get current schema if not specified
            if not database:
                cursor.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL")
                database = cursor.fetchone()[0]

            # Get column information
            cursor.execute("""
                SELECT
                    column_name,
                    data_type,
                    nullable,
                    data_default
                FROM all_tab_columns
                WHERE table_name = :table_name
                AND owner = :owner
                ORDER BY column_id
            """, table_name=table, owner=database)

            columns = []
            for row in cursor.fetchall():
                columns.append({
                    'name': row[0],
                    'type': row[1],
                    'nullable': row[2] == 'Y',
                    'default': row[3],
                    'primary_key': False  # Will be updated below
                })

            # Get primary keys
            cursor.execute("""
                SELECT cols.column_name
                FROM all_constraints cons
                JOIN all_cons_columns cols
                    ON cons.constraint_name = cols.constraint_name
                    AND cons.owner = cols.owner
                WHERE cons.constraint_type = 'P'
                AND cons.table_name = :table_name
                AND cons.owner = :owner
            """, table_name=table, owner=database)

            pk_columns = {row[0] for row in cursor.fetchall()}
            for col in columns:
                if col['name'] in pk_columns:
                    col['primary_key'] = True

            # Get indexes
            cursor.execute("""
                SELECT
                    i.index_name,
                    ic.column_name
                FROM all_indexes i
                JOIN all_ind_columns ic
                    ON i.index_name = ic.index_name
                    AND i.owner = ic.index_owner
                WHERE i.table_name = :table_name
                AND i.owner = :owner
                ORDER BY i.index_name, ic.column_position
            """, table_name=table, owner=database)

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
                    cols.column_name,
                    ref_cons.table_name as referenced_table,
                    ref_cols.column_name as referenced_column
                FROM all_constraints cons
                JOIN all_cons_columns cols
                    ON cons.constraint_name = cols.constraint_name
                    AND cons.owner = cols.owner
                JOIN all_constraints ref_cons
                    ON cons.r_constraint_name = ref_cons.constraint_name
                    AND cons.r_owner = ref_cons.owner
                JOIN all_cons_columns ref_cols
                    ON ref_cons.constraint_name = ref_cols.constraint_name
                    AND ref_cons.owner = ref_cols.owner
                WHERE cons.constraint_type = 'R'
                AND cons.table_name = :table_name
                AND cons.owner = :owner
            """, table_name=table, owner=database)

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
        """Execute a SQL query on Oracle database."""
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
                row_data = [{col: serialize_value(val) for col, val in zip(columns, row)} for row in rows]
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
        """Get paginated data from an Oracle table."""
        try:
            # Build query with Oracle pagination (OFFSET/FETCH)
            raw_table = table
            table = self.qualified(database, table)

            exact, search_cols, term = self.split_search(raw_table, database, filters)
            conditions, values = [], []
            for col, val in exact.items():
                if val is None:
                    conditions.append(f"{self.q(col)} IS NULL")
                else:
                    values.append(val)
                    conditions.append(f"{self.q(col)} = :{len(values)}")
            if term:
                like = []
                for c in search_cols:
                    values.append(f'%{term}%')
                    like.append(f'UPPER(CAST("{c}" AS VARCHAR2(4000))) LIKE UPPER(:{len(values)})')
                conditions.append("(" + " OR ".join(like) + ")")
            where = " WHERE " + " AND ".join(conditions) if conditions else ""

            query = f"SELECT * FROM {table}{where}"

            # Add sorting
            if sort_by:
                query += f" ORDER BY {self.q(sort_by)} {sort_order}"

            # Add pagination (Oracle 12c+ syntax)
            query += f" OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"

            # Execute query
            result = self.execute_query(query, values)

            # Get total count
            cursor = self.connection.cursor()
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}{where}", values)
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
        """Insert a new row into an Oracle table."""
        try:
            table = self.qualified(database, table)

            columns = ', '.join(self.q(c) for c in data.keys())
            placeholders = ', '.join([f":{i}" for i in range(len(data))])
            query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

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
        """Update row(s) in an Oracle table."""
        try:
            table = self.qualified(database, table)

            # Build SET clause
            set_clause = ', '.join([f"{self.q(col)} = :{i}" for i, col in enumerate(data.keys())])

            # Build WHERE clause
            where_clause = ' AND '.join([f"{self.q(col)} = :{i + len(data)}" for i, col in enumerate(conditions.keys())])

            query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
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
        """Delete row(s) from an Oracle table."""
        try:
            table = self.qualified(database, table)

            # Build WHERE clause
            where_clause = ' AND '.join([f"{self.q(col)} = :{i}" for i, col in enumerate(conditions.keys())])

            query = f"DELETE FROM {table} WHERE {where_clause}"
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
