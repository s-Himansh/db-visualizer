import logging
logger = logging.getLogger(__name__)
import redis
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from .base import BaseConnector


class RedisConnector(BaseConnector):
    """Redis database connector implementation."""

    SUPPORTS_PROFILE = False

    MAX_KEYS = 100_000

    def connect(self) -> bool:
        """Establish connection to Redis database."""
        try:
            # Check if connection URL is provided
            connection_url = self.connection_params.get('connection_url')

            if connection_url:
                # Use connection URL directly
                self.connection = redis.from_url(connection_url, decode_responses=True)
            else:
                # Build connection from individual fields
                host = self.connection_params.get('host', 'localhost')
                port = self.connection_params.get('port', 6379)
                password = self.connection_params.get('password')
                db = self.connection_params.get('database', 0)

                conn_params = {
                    'host': host,
                    'port': port,
                    'db': db,
                    'decode_responses': True
                }

                if password:
                    conn_params['password'] = password

                self.connection = redis.Redis(**conn_params)

            # Test connection
            self.connection.ping()
            return True
        except Exception as e:
            logger.error(f"Redis connection error: {e}")
            return False

    def ping(self) -> bool:
        try:
            return bool(self.connection.ping())
        except Exception:
            return False

    def disconnect(self) -> bool:
        """Close the Redis connection."""
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
            return True
        except Exception as e:
            logger.error(f"Redis disconnection error: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """Test the Redis connection."""
        try:
            if self.connect():
                self.connection.ping()
                self.disconnect()
                return True, "Connection successful"
            return False, "Failed to connect"
        except Exception as e:
            self.disconnect()
            return False, f"Connection test failed: {str(e)}"

    def get_databases(self) -> List[str]:
        """
        Get list of Redis databases (0-15 by default).
        """
        try:
            # Redis has numbered databases (usually 0-15)
            # We'll return the configured databases
            info = self.connection.info('keyspace')
            databases = []

            # Add databases that have keys
            for key in info.keys():
                if key.startswith('db'):
                    db_num = key[2:]  # Extract number from "db0", "db1", etc.
                    databases.append(f"db{db_num}")

            # If no databases have keys, show db0
            if not databases:
                databases = ['db0']

            return databases
        except Exception as e:
            logger.error(f"Error getting databases: {e}")
            return ['db0']

    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get key patterns from Redis.
        Redis doesn't have tables, so we'll group keys by pattern.
        """
        try:
            # Switch database if specified
            if database:
                db_num = int(database.replace('db', ''))
                self.connection.execute_command('SELECT', db_num)

            # Get all keys (limited to 1000 for performance)
            cursor = 0
            all_keys = []
            max_keys = 1000

            while len(all_keys) < max_keys:
                cursor, keys = self.connection.scan(cursor, count=100)
                all_keys.extend(keys)
                if cursor == 0:
                    break

            # Group keys by prefix (before first colon)
            key_groups = {}
            for key in all_keys:
                # Get key type
                key_type = self.connection.type(key)

                # Extract prefix
                if ':' in key:
                    prefix = key.split(':', 1)[0]
                else:
                    prefix = 'default'

                if prefix not in key_groups:
                    key_groups[prefix] = {
                        'count': 0,
                        'types': set()
                    }

                key_groups[prefix]['count'] += 1
                key_groups[prefix]['types'].add(key_type)

            # Convert to table format
            tables = []
            for prefix, info in key_groups.items():
                tables.append({
                    'name': f"{prefix}:*",
                    'type': ', '.join(info['types']),
                    'rows': info['count']
                })

            # Add an "All Keys" group
            if all_keys:
                tables.insert(0, {
                    'name': '*',
                    'type': 'all',
                    'rows': len(all_keys)
                })

            return tables
        except Exception as e:
            logger.error(f"Error getting keys: {e}")
            return []

    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """
        Get schema for a Redis key pattern.
        Returns sample keys and their types.
        """
        try:
            # Switch database if specified
            if database:
                db_num = int(database.replace('db', ''))
                self.connection.execute_command('SELECT', db_num)

            # Get sample keys matching the pattern
            cursor = 0
            sample_keys = []
            max_samples = 20

            while len(sample_keys) < max_samples:
                cursor, keys = self.connection.scan(cursor, match=table, count=100)
                sample_keys.extend(keys[:max_samples - len(sample_keys)])
                if cursor == 0:
                    break

            # Analyze key types and structures
            columns = []
            for key in sample_keys:
                key_type = self.connection.type(key)
                ttl = self.connection.ttl(key)

                columns.append({
                    'name': key,
                    'type': key_type,
                    'nullable': False,
                    'default': None,
                    'primary_key': True,
                    'ttl': ttl if ttl > 0 else None
                })

            return {
                'columns': columns,
                'indexes': [],
                'constraints': [],
                'foreign_keys': []
            }
        except Exception as e:
            logger.error(f"Error getting schema: {e}")
            return {'columns': [], 'indexes': [], 'constraints': [], 'foreign_keys': []}

    def execute_query(self, query: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute a Redis command.
        Query should be a Redis command string (e.g., "GET mykey" or "KEYS *")
        """
        start_time = time.time()

        try:
            # Split command into parts
            parts = query.strip().split()
            if not parts:
                return {
                    'columns': [],
                    'rows': [],
                    'row_count': 0,
                    'execution_time': 0,
                    'error': 'Empty command'
                }

            command = parts[0].upper()
            args = parts[1:]

            # Execute command
            result = self.connection.execute_command(command, *args)

            # Format result
            if isinstance(result, list):
                rows = [{'value': str(item)} for item in result]
                columns = ['value']
            elif isinstance(result, dict):
                rows = [result]
                columns = list(result.keys()) if result else []
            elif result is not None:
                rows = [{'value': str(result)}]
                columns = ['value']
            else:
                rows = []
                columns = []

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
        """Get keys matching the pattern with their values."""
        try:
            # Switch database if specified
            if database:
                db_num = int(database.replace('db', ''))
                self.connection.execute_command('SELECT', db_num)

            # SCAN returns keys in arbitrary order and may repeat them, so collect, de-duplicate and sort:
            # that is what makes the total, the page boundaries and "Next" correct.
            # shortcut: capped at MAX_KEYS matches; upgrade to a cursor-based pager for bigger keyspaces.
            all_keys = set()
            for key in self.connection.scan_iter(match=table, count=1000):
                all_keys.add(key)
                if len(all_keys) >= self.MAX_KEYS:
                    break

            term = (filters or {}).get('search_term')
            if term:
                all_keys = {k for k in all_keys if term.lower() in k.lower()}

            all_keys = sorted(all_keys, reverse=(sort_order or '').upper() == 'DESC')
            paginated_keys = all_keys[offset:offset + limit]

            # Get values for each key
            rows = []
            for key in paginated_keys:
                key_type = self.connection.type(key)
                ttl = self.connection.ttl(key)

                # Get value based on type
                value = None
                if key_type == 'string':
                    value = self.connection.get(key)
                elif key_type == 'list':
                    value = self.connection.lrange(key, 0, 10)  # First 10 items
                elif key_type == 'set':
                    value = list(self.connection.smembers(key))[:10]  # First 10 members
                elif key_type == 'zset':
                    value = self.connection.zrange(key, 0, 10)  # First 10 items
                elif key_type == 'hash':
                    value = self.connection.hgetall(key)

                rows.append({
                    'key': key,
                    'type': key_type,
                    'value': str(value),
                    'ttl': ttl if ttl > 0 else None
                })

            columns = ['key', 'type', 'value', 'ttl']
            total_count = len(all_keys)

            return {
                'columns': columns,
                'rows': rows,
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
        """Set a key-value pair in Redis."""
        try:
            # Switch database if specified
            if database:
                db_num = int(database.replace('db', ''))
                self.connection.execute_command('SELECT', db_num)

            key = data.get('key')
            value = data.get('value')
            ttl = data.get('ttl')

            if not key:
                return False, "Key is required"

            # Set value
            self.connection.set(key, value)

            # Set TTL if provided
            if ttl and ttl > 0:
                self.connection.expire(key, int(ttl))

            return True, f"Key '{key}' set successfully"
        except Exception as e:
            return False, f"Insert failed: {str(e)}"

    def update_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        data: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Update a key's value in Redis."""
        try:
            # Switch database if specified
            if database:
                db_num = int(database.replace('db', ''))
                self.connection.execute_command('SELECT', db_num)

            key = conditions.get('key')
            value = data.get('value')

            if not key:
                return False, "Key is required in conditions"

            # Check if key exists
            if not self.connection.exists(key):
                return False, f"Key '{key}' does not exist"

            # Update value
            self.connection.set(key, value)

            # Update TTL if provided
            if 'ttl' in data and data['ttl']:
                self.connection.expire(key, int(data['ttl']))

            return True, f"Key '{key}' updated successfully"
        except Exception as e:
            return False, f"Update failed: {str(e)}"

    def delete_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Delete a key from Redis."""
        try:
            # Switch database if specified
            if database:
                db_num = int(database.replace('db', ''))
                self.connection.execute_command('SELECT', db_num)

            key = conditions.get('key')

            if not key:
                return False, "Key is required in conditions"

            # Delete key
            result = self.connection.delete(key)

            if result > 0:
                return True, f"Key '{key}' deleted successfully"
            else:
                return False, f"Key '{key}' does not exist"
        except Exception as e:
            return False, f"Delete failed: {str(e)}"
