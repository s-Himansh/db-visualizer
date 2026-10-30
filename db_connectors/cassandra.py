import logging
logger = logging.getLogger(__name__)
from cassandra.cluster import Cluster, ExecutionProfile, EXEC_PROFILE_DEFAULT
from cassandra.policies import DCAwareRoundRobinPolicy, TokenAwarePolicy
from cassandra.auth import PlainTextAuthProvider
from cassandra import ConsistencyLevel
from cassandra.query import SimpleStatement
import ssl
import time
from typing import Any, Dict, List, Optional, Tuple
from .base import BaseConnector


class CassandraConnector(BaseConnector):
    """Cassandra database connector implementation."""

    SUPPORTS_PROFILE = False

    def connect(self) -> bool:
        """Establish connection to Cassandra cluster."""
        try:
            # Get connection parameters
            contact_points = self.connection_params.get('host', 'localhost').split(',')
            contact_points = [cp.strip() for cp in contact_points]
            port = int(self.connection_params.get('port', 9042))
            username = self.connection_params.get('username')
            password = self.connection_params.get('password')
            # Support both 'keyspace' and 'database' parameters
            keyspace = self.connection_params.get('keyspace') or self.connection_params.get('database')
            use_ssl = self.connection_params.get('use_ssl', False)

            # Setup authentication if provided
            auth_provider = None
            if username and password:
                auth_provider = PlainTextAuthProvider(username=username, password=password)

            # Setup SSL if enabled
            ssl_context = None
            if use_ssl:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

                # Load certificate files if provided
                ca_cert = self.connection_params.get('ca_cert_path')
                client_cert = self.connection_params.get('client_cert_path')
                client_key = self.connection_params.get('client_key_path')

                if ca_cert:
                    ssl_context.load_verify_locations(ca_cert)
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                else:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                if client_cert and client_key:
                    ssl_context.load_cert_chain(certfile=client_cert, keyfile=client_key)

            # Create execution profile
            profile = ExecutionProfile(
                load_balancing_policy=TokenAwarePolicy(DCAwareRoundRobinPolicy()),
                request_timeout=30
            )

            # Create cluster connection
            self.cluster = Cluster(
                contact_points=contact_points,
                port=port,
                auth_provider=auth_provider,
                ssl_context=ssl_context,
                execution_profiles={EXEC_PROFILE_DEFAULT: profile},
                protocol_version=4
            )

            # Connect to cluster
            self.connection = self.cluster.connect(keyspace=keyspace)

            # Store keyspace for later use
            self.current_keyspace = keyspace

            return True
        except Exception as e:
            logger.error(f"Cassandra connection error: {e}")
            return False

    def ping(self) -> bool:
        try:
            self.connection.execute('SELECT now() FROM system.local')
            return True
        except Exception:
            return False

    def disconnect(self) -> bool:
        """Close the Cassandra connection."""
        try:
            if self.connection:
                self.connection.shutdown()
                self.connection = None
            if self.cluster:
                self.cluster.shutdown()
                self.cluster = None
            return True
        except Exception as e:
            logger.error(f"Cassandra disconnection error: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """Test the Cassandra connection."""
        try:
            if self.connect():
                # Test query
                self.connection.execute("SELECT now() FROM system.local")
                self.disconnect()
                return True, "Connection successful"
            return False, "Failed to connect"
        except Exception as e:
            self.disconnect()
            return False, f"Connection test failed: {str(e)}"

    def get_databases(self) -> List[str]:
        """Get list of all Cassandra keyspaces."""
        try:
            rows = self.connection.execute(
                "SELECT keyspace_name FROM system_schema.keyspaces"
            )
            # Filter out system keyspaces
            keyspaces = [row.keyspace_name for row in rows
                        if not row.keyspace_name.startswith('system')]
            return keyspaces
        except Exception as e:
            logger.error(f"Error getting keyspaces: {e}")
            return []

    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all tables in the specified Cassandra keyspace."""
        try:
            keyspace = database or self.current_keyspace
            if not keyspace:
                return []

            rows = self.connection.execute(
                """
                SELECT table_name
                FROM system_schema.tables
                WHERE keyspace_name = %s
                """,
                (keyspace,)
            )

            # Cassandra cannot count rows cheaply (COUNT(*) scans the cluster), so no counts are shown
            tables = [{'name': row.table_name, 'type': 'table', 'rows': None, 'rows_estimated': True} for row in rows]

            return tables
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return []

    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """Get the schema of a Cassandra table."""
        try:
            keyspace = database or self.current_keyspace
            if not keyspace:
                return {'columns': [], 'indexes': [], 'constraints': [], 'foreign_keys': []}

            # Get column information
            rows = self.connection.execute(
                """
                SELECT column_name, type, kind
                FROM system_schema.columns
                WHERE keyspace_name = %s AND table_name = %s
                """,
                (keyspace, table)
            )

            columns = []
            partition_keys = []
            clustering_keys = []

            for row in rows:
                column_info = {
                    'name': row.column_name,
                    'type': row.type,
                    'nullable': True,
                    'default': None,
                    'primary_key': False
                }

                if row.kind == 'partition_key':
                    column_info['primary_key'] = True
                    partition_keys.append(row.column_name)
                elif row.kind == 'clustering':
                    clustering_keys.append(row.column_name)

                columns.append(column_info)

            # Get indexes
            index_rows = self.connection.execute(
                """
                SELECT index_name, options
                FROM system_schema.indexes
                WHERE keyspace_name = %s AND table_name = %s
                """,
                (keyspace, table)
            )

            indexes = []
            for row in index_rows:
                if row.index_name:
                    indexes.append({
                        'name': row.index_name,
                        'columns': [row.options.get('target', '')],
                        'unique': False
                    })

            # Add metadata about partition and clustering keys
            constraints = []
            if partition_keys:
                constraints.append({
                    'type': 'PARTITION KEY',
                    'columns': partition_keys
                })
            if clustering_keys:
                constraints.append({
                    'type': 'CLUSTERING KEY',
                    'columns': clustering_keys
                })

            return {
                'columns': columns,
                'indexes': indexes,
                'constraints': constraints,
                'foreign_keys': []
            }
        except Exception as e:
            logger.error(f"Error getting schema: {e}")
            return {'columns': [], 'indexes': [], 'constraints': [], 'foreign_keys': []}

    def execute_query(self, query: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute a CQL query."""
        start_time = time.time()

        try:
            # Execute the query
            statement = SimpleStatement(query, consistency_level=ConsistencyLevel.ONE)
            result = self.connection.execute(statement)

            # Get column names
            columns = []
            if result.column_names:
                columns = list(result.column_names)

            # Get rows
            rows = []
            for row in result:
                row_dict = {}
                for i, col_name in enumerate(columns):
                    row_dict[col_name] = row[i]
                rows.append(row_dict)

            execution_time = time.time() - start_time

            return {
                'columns': columns,
                'rows': rows,
                'row_count': len(rows),
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
        """Get paginated data from a Cassandra table."""
        try:
            keyspace = database or self.current_keyspace
            if not keyspace:
                return {
                    'columns': [],
                    'rows': [],
                    'total_count': 0,
                    'has_more': False
                }

            # Build CQL query
            query = f"SELECT * FROM {self.q(keyspace)}.{self.q(table)}"

            # Add filters
            where_clauses = []
            filter_values = []

            if filters:
                # Handle search filters
                if 'search_term' in filters and filters['search_term']:
                    # Note: Cassandra doesn't support LIKE, so search is limited
                    # This is a basic implementation
                    search_column = filters.get('search_column')
                    if search_column:
                        where_clauses.append(f"{self.q(search_column)} = %s")
                        filter_values.append(filters['search_term'])

                # Handle other filters
                for col, val in filters.items():
                    if col not in ['search_term', 'search_column']:
                        where_clauses.append(f"{self.q(col)} = %s")
                        filter_values.append(val)

            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            # CQL has no OFFSET: read offset+limit rows and drop the first `offset` ones.
            # ALLOW FILTERING is needed to filter on non-key columns (a full scan, acceptable for a browser).
            query += f" LIMIT {offset + limit}"
            if where_clauses:
                query += " ALLOW FILTERING"

            result = self.connection.execute(query, filter_values if filter_values else None)

            # Get columns
            columns = list(result.column_names) if result.column_names else []

            # Get rows
            rows = []
            for n, row in enumerate(result):
                if n < offset:
                    continue
                rows.append({col_name: row[i] for i, col_name in enumerate(columns)})

            # Get total count (expensive operation in Cassandra)
            try:
                count_query = f"SELECT COUNT(*) FROM {self.q(keyspace)}.{self.q(table)}"
                if where_clauses:
                    count_query += " WHERE " + " AND ".join(where_clauses) + " ALLOW FILTERING"
                count_result = self.connection.execute(count_query, filter_values if filter_values else None)
                total_count = count_result.one()[0]
            except Exception as e:
                logger.warning(f"Could not count rows: {e}")
                total_count = offset + len(rows)

            return {
                'columns': columns,
                'rows': rows,
                'total_count': total_count,
                'has_more': offset + len(rows) < total_count
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
        """Insert a new row into a Cassandra table."""
        try:
            keyspace = database or self.current_keyspace
            if not keyspace:
                return False, "No keyspace selected"

            columns = list(data.keys())
            placeholders = ', '.join(['%s'] * len(columns))
            column_names = ', '.join(self.q(c) for c in columns)

            query = f"INSERT INTO {self.q(keyspace)}.{self.q(table)} ({column_names}) VALUES ({placeholders})"

            self.connection.execute(query, list(data.values()))

            return True, "Row inserted successfully"
        except Exception as e:
            return False, f"Insert failed: {str(e)}"

    def update_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        data: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Update row(s) in a Cassandra table."""
        try:
            keyspace = database or self.current_keyspace
            if not keyspace:
                return False, "No keyspace selected"

            # Build SET clause
            set_clauses = [f"{self.q(col)} = %s" for col in data.keys()]
            set_values = list(data.values())

            # Build WHERE clause
            where_clauses = [f"{self.q(col)} = %s" for col in conditions.keys()]
            where_values = list(conditions.values())

            # CQL UPDATE is an upsert: editing a row that was deleted (or never existed) would silently
            # create it. Check first. (IF EXISTS is not used: lightweight-transaction timestamps can
            # outrank an immediately following normal DELETE and resurrect the row.)
            exists = self.connection.execute(
                f"SELECT {self.q(next(iter(conditions)))} FROM {self.q(keyspace)}.{self.q(table)} WHERE {' AND '.join(where_clauses)} LIMIT 1",
                where_values).one()
            if exists is None:
                return False, "No matching row to update (it may have been deleted)"

            query = f"UPDATE {self.q(keyspace)}.{self.q(table)} SET {', '.join(set_clauses)} WHERE {' AND '.join(where_clauses)}"
            self.connection.execute(query, set_values + where_values)

            return True, "Row updated successfully"
        except Exception as e:
            return False, f"Update failed: {str(e)}"

    def delete_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Delete row(s) from a Cassandra table."""
        try:
            keyspace = database or self.current_keyspace
            if not keyspace:
                return False, "No keyspace selected"

            # Build WHERE clause
            where_clauses = [f"{self.q(col)} = %s" for col in conditions.keys()]
            where_values = list(conditions.values())

            query = f"DELETE FROM {self.q(keyspace)}.{self.q(table)} WHERE {' AND '.join(where_clauses)}"

            self.connection.execute(query, where_values)

            return True, "Row deleted successfully"
        except Exception as e:
            return False, f"Delete failed: {str(e)}"
