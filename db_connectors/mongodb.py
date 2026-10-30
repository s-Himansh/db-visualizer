import logging
logger = logging.getLogger(__name__)
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import re
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


class MongoDBConnector(BaseConnector):
    """MongoDB database connector implementation."""

    SUPPORTS_PROFILE = False

    def connect(self) -> bool:
        """Establish connection to MongoDB database."""
        try:
            from urllib.parse import urlparse

            # Check if connection URL is provided
            connection_url = self.connection_params.get('connection_url')
            use_ssl = self.connection_params.get('use_ssl', False)

            if connection_url:
                # Use connection URL directly
                uri = connection_url

                # Extract database from URL if present and not already in connection_params
                if not self.connection_params.get('database'):
                    parsed = urlparse(uri)
                    # Path is like "/database" so strip the leading slash
                    if parsed.path and len(parsed.path) > 1:
                        db_from_url = parsed.path.lstrip('/').split('?')[0]
                        if db_from_url:
                            self.connection_params['database'] = db_from_url

                # Add SSL parameter to URL if enabled and not already present
                if use_ssl and 'ssl=' not in uri.lower() and 'tls=' not in uri.lower():
                    separator = '&' if '?' in uri else '?'
                    uri += f"{separator}ssl=true"
            else:
                # Build connection string from individual fields
                host = self.connection_params.get('host', 'localhost')
                port = self.connection_params.get('port', 27017)
                username = self.connection_params.get('username')
                password = self.connection_params.get('password')
                database = self.connection_params.get('database', 'admin')

                if username and password:
                    uri = f"mongodb://{username}:{password}@{host}:{port}/{database}"
                else:
                    uri = f"mongodb://{host}:{port}/{database}"

                # Add SSL parameter if enabled
                if use_ssl:
                    uri += "?ssl=true"

            self.connection = MongoClient(uri, serverSelectionTimeoutMS=5000)
            # Test connection
            self.connection.admin.command('ping')
            return True
        except Exception as e:
            logger.error(f"MongoDB connection error: {e}")
            return False

    def ping(self) -> bool:
        try:
            self.connection.admin.command('ping')
            return True
        except Exception:
            return False

    def disconnect(self) -> bool:
        """Close the MongoDB connection."""
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
            return True
        except Exception as e:
            logger.error(f"MongoDB disconnection error: {e}")
            return False

    def test_connection(self) -> Tuple[bool, str]:
        """Test the MongoDB connection."""
        try:
            if self.connect():
                self.connection.admin.command('ping')
                self.disconnect()
                return True, "Connection successful"
            return False, "Failed to connect"
        except Exception as e:
            self.disconnect()
            return False, f"Connection test failed: {str(e)}"

    def get_databases(self) -> List[str]:
        """Get list of all MongoDB databases."""
        try:
            databases = self.connection.list_database_names()
            # Filter out admin and config databases
            return [db for db in databases if db not in ['admin', 'config', 'local']]
        except Exception as e:
            logger.error(f"Error getting databases: {e}")
            return []

    def get_tables(self, database: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all collections in the specified MongoDB database."""
        try:
            if not database:
                database = self.connection_params.get('database', 'admin')

            db = self.connection[database]
            collections = db.list_collection_names()

            tables = []
            for coll_name in collections:
                # Get document count
                try:
                    count = db[coll_name].count_documents({})
                except:
                    count = None

                tables.append({
                    'name': coll_name,
                    'type': 'collection',
                    'rows': count
                })

            return tables
        except Exception as e:
            logger.error(f"Error getting collections: {e}")
            return []

    def get_schema(self, table: str, database: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the schema of a MongoDB collection.
        Since MongoDB is schema-less, we'll sample documents to infer structure.
        """
        try:
            if not database:
                database = self.connection_params.get('database', 'admin')

            db = self.connection[database]
            collection = db[table]

            # Sample first 100 documents to infer schema
            sample_docs = list(collection.find().limit(100))

            if not sample_docs:
                return {'columns': [], 'indexes': [], 'constraints': [], 'foreign_keys': []}

            # Collect all unique fields
            field_types = {}
            for doc in sample_docs:
                for key, value in doc.items():
                    field_type = type(value).__name__
                    if key not in field_types:
                        field_types[key] = set()
                    field_types[key].add(field_type)

            # Build column list
            columns = []
            for field, types in field_types.items():
                columns.append({
                    'name': field,
                    'type': ', '.join(types),  # May have multiple types
                    'nullable': True,  # MongoDB fields are always optional
                    'default': None,
                    'primary_key': field == '_id'
                })

            # Get indexes
            indexes = []
            for idx in collection.list_indexes():
                idx_info = {
                    'name': idx['name'],
                    'columns': list(idx['key'].keys()),
                    'unique': idx.get('unique', False)
                }
                indexes.append(idx_info)

            return {
                'columns': columns,
                'indexes': indexes,
                'constraints': [],
                'foreign_keys': []
            }
        except Exception as e:
            logger.error(f"Error getting schema: {e}")
            return {'columns': [], 'indexes': [], 'constraints': [], 'foreign_keys': []}

    def execute_query(self, query: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Execute a MongoDB query.
        Query should be a JSON string representing the find filter.
        """
        start_time = time.time()

        try:
            import json
            import re

            # Parse query as JSON
            try:
                # Remove JavaScript-style comments before parsing
                query_str = query if isinstance(query, str) else str(query)
                # Remove single-line comments (// ...)
                query_str = re.sub(r'//.*?$', '', query_str, flags=re.MULTILINE)
                # Remove multi-line comments (/* ... */)
                query_str = re.sub(r'/\*.*?\*/', '', query_str, flags=re.DOTALL)
                # Remove leading/trailing whitespace
                query_str = query_str.strip()

                query_dict = json.loads(query_str)
            except json.JSONDecodeError as e:
                return {
                    'columns': [],
                    'rows': [],
                    'row_count': 0,
                    'execution_time': 0,
                    'error': f'Invalid JSON query: {str(e)}'
                }

            # Extract database and collection from query
            database = query_dict.get('database') or self.connection_params.get('database', 'admin')
            collection_name = query_dict.get('collection')

            if not collection_name:
                return {
                    'columns': [],
                    'rows': [],
                    'row_count': 0,
                    'execution_time': 0,
                    'error': 'Collection name not specified in query'
                }

            db = self.connection[database]
            collection = db[collection_name]

            # Execute query
            filter_query = query_dict.get('filter', {})
            projection = query_dict.get('projection')
            limit_val = query_dict.get('limit', 100)
            skip_val = query_dict.get('skip', 0)
            sort_val = query_dict.get('sort')

            cursor = collection.find(filter_query, projection).skip(skip_val).limit(limit_val).max_time_ms(60_000)

            if sort_val:
                cursor = cursor.sort(list(sort_val.items()))

            results = list(cursor)

            # Convert ObjectId to string and serialize datetime values
            for doc in results:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
                # Serialize datetime values
                for key, value in doc.items():
                    doc[key] = serialize_value(value)

            # Get column names
            columns = []
            if results:
                columns = list(results[0].keys())

            execution_time = time.time() - start_time

            return {
                'columns': columns,
                'rows': results,
                'row_count': len(results),
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
        """Get paginated data from a MongoDB collection."""
        try:
            if not database:
                database = self.connection_params.get('database', 'admin')

            db = self.connection[database]
            collection = db[table]

            # Build query
            query, search_cols, term = self.split_search(table, database, filters)
            if term and search_cols:
                # Match against each field's text form so numbers, dates and ids are searchable too
                query['$or'] = [{'$expr': {'$regexMatch': {
                    'input': {'$convert': {'input': f'${c}', 'to': 'string', 'onError': ''}},
                    'regex': re.escape(term), 'options': 'i'}}} for c in search_cols]

            # Execute query
            cursor = collection.find(query).skip(offset).limit(limit)

            # Add sorting
            if sort_by:
                sort_direction = 1 if sort_order.upper() == 'ASC' else -1
                cursor = cursor.sort(sort_by, sort_direction)

            results = list(cursor)

            # Convert ObjectId to string and serialize datetime values
            for doc in results:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
                # Serialize datetime values
                for key, value in doc.items():
                    doc[key] = serialize_value(value)

            # Get columns
            columns = []
            if results:
                columns = list(results[0].keys())

            # Get total count
            total_count = collection.count_documents(query)

            return {
                'columns': columns,
                'rows': results,
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
        """Insert a new document into a MongoDB collection."""
        try:
            if not database:
                database = self.connection_params.get('database', 'admin')

            db = self.connection[database]
            collection = db[table]

            result = collection.insert_one(data)

            return True, f"Document inserted successfully (ID: {result.inserted_id})"
        except Exception as e:
            return False, f"Insert failed: {str(e)}"

    def update_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        data: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Update document(s) in a MongoDB collection."""
        try:
            if not database:
                database = self.connection_params.get('database', 'admin')

            db = self.connection[database]
            collection = db[table]

            # Convert _id string to ObjectId if present in conditions
            if '_id' in conditions and isinstance(conditions['_id'], str):
                from bson import ObjectId
                try:
                    conditions['_id'] = ObjectId(conditions['_id'])
                except:
                    pass

            result = collection.update_many(conditions, {'$set': data})

            return True, f"{result.modified_count} document(s) updated"
        except Exception as e:
            return False, f"Update failed: {str(e)}"

    def delete_row(
        self,
        table: str,
        conditions: Dict[str, Any],
        database: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Delete document(s) from a MongoDB collection."""
        try:
            if not database:
                database = self.connection_params.get('database', 'admin')

            db = self.connection[database]
            collection = db[table]

            # Convert _id string to ObjectId if present in conditions
            if '_id' in conditions and isinstance(conditions['_id'], str):
                from bson import ObjectId
                try:
                    conditions['_id'] = ObjectId(conditions['_id'])
                except:
                    pass

            result = collection.delete_many(conditions)

            return True, f"{result.deleted_count} document(s) deleted"
        except Exception as e:
            return False, f"Delete failed: {str(e)}"
