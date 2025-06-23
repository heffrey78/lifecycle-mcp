#!/usr/bin/env python3
"""
Database Manager for Lifecycle MCP Server
Provides centralized database connection and operation management
"""

import sqlite3
import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Centralized database manager for lifecycle MCP operations"""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database manager with connection path"""
        self.db_path = db_path or os.environ.get("LIFECYCLE_DB", "lifecycle.db")
        self._ensure_database_exists()
    
    def _ensure_database_exists(self):
        """Initialize database with schema if needed"""
        if not Path(self.db_path).exists():
            logger.info(f"Creating new database at {self.db_path}")
            conn = sqlite3.connect(self.db_path)
            schema_path = Path(__file__).parent / "lifecycle-schema.sql"
            if schema_path.exists():
                with open(schema_path, "r") as f:
                    conn.executescript(f.read())
                logger.info("Database schema initialized")
            conn.close()
    
    @contextmanager
    def get_connection(self, row_factory: bool = False):
        """Context manager for database connections with automatic cleanup"""
        conn = sqlite3.connect(self.db_path)
        if row_factory:
            conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            logger.error(f"Database operation failed: {str(e)}")
            raise
        finally:
            conn.close()
    
    def execute_query(self, query: str, params: Optional[List[Any]] = None, 
                     fetch_one: bool = False, fetch_all: bool = False,
                     row_factory: bool = False) -> Optional[Union[List, sqlite3.Row]]:
        """Execute a query and return results"""
        params = params or []
        
        with self.get_connection(row_factory=row_factory) as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            
            if fetch_one:
                return cur.fetchone()
            elif fetch_all:
                return cur.fetchall()
            else:
                # For INSERT/UPDATE/DELETE operations
                conn.commit()
                return cur.lastrowid
    
    def execute_many(self, query: str, params_list: List[List[Any]]) -> None:
        """Execute a query multiple times with different parameters"""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.executemany(query, params_list)
            conn.commit()
    
    @contextmanager
    def transaction(self, row_factory: bool = False):
        """Context manager for database transactions"""
        conn = sqlite3.connect(self.db_path)
        if row_factory:
            conn.row_factory = sqlite3.Row
        
        try:
            yield conn.cursor()
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction failed: {str(e)}")
            raise
        finally:
            conn.close()
    
    def get_next_id(self, table: str, id_column: str, where_clause: str = "", 
                   where_params: Optional[List[Any]] = None) -> int:
        """Get next available ID for a table with optional filtering"""
        where_params = where_params or []
        
        if where_clause:
            query = f"SELECT COALESCE(MAX({id_column}), 0) + 1 FROM {table} WHERE {where_clause}"
        else:
            query = f"SELECT COALESCE(MAX({id_column}), 0) + 1 FROM {table}"
        
        result = self.execute_query(query, where_params, fetch_one=True)
        return result[0] if result else 1
    
    def check_exists(self, table: str, where_clause: str, 
                    where_params: List[Any]) -> bool:
        """Check if a record exists in the table"""
        query = f"SELECT 1 FROM {table} WHERE {where_clause} LIMIT 1"
        result = self.execute_query(query, where_params, fetch_one=True)
        return result is not None
    
    def insert_record(self, table: str, data: Dict[str, Any]) -> Optional[int]:
        """Insert a record into the table and return the row ID"""
        columns = list(data.keys())
        placeholders = ["?" for _ in columns]
        values = list(data.values())
        
        query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
        return self.execute_query(query, values)
    
    def update_record(self, table: str, data: Dict[str, Any], 
                     where_clause: str, where_params: List[Any]) -> None:
        """Update records in the table"""
        set_clauses = [f"{column} = ?" for column in data.keys()]
        values = list(data.values()) + where_params
        
        query = f"UPDATE {table} SET {', '.join(set_clauses)} WHERE {where_clause}"
        self.execute_query(query, values)
    
    def delete_record(self, table: str, where_clause: str, 
                     where_params: List[Any]) -> None:
        """Delete records from the table"""
        query = f"DELETE FROM {table} WHERE {where_clause}"
        self.execute_query(query, where_params)
    
    def get_records(self, table: str, columns: str = "*", 
                   where_clause: str = "", where_params: Optional[List[Any]] = None,
                   order_by: str = "", limit: Optional[int] = None,
                   row_factory: bool = True) -> List[sqlite3.Row]:
        """Get records from the table with optional filtering and ordering"""
        where_params = where_params or []
        
        query = f"SELECT {columns} FROM {table}"
        
        if where_clause:
            query += f" WHERE {where_clause}"
        
        if order_by:
            query += f" ORDER BY {order_by}"
        
        if limit:
            query += f" LIMIT {limit}"
        
        return self.execute_query(query, where_params, fetch_all=True, row_factory=row_factory)