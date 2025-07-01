#!/usr/bin/env python3
"""
Database Manager for Lifecycle MCP Server
Provides centralized database connection and operation management
"""

import sqlite3
import os
import logging
import time
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from contextlib import contextmanager
from queue import Queue, Empty, Full

from .migrations import apply_all_migrations

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Thread-safe SQLite connection pool"""
    
    def __init__(self, db_path: str, pool_size: int = 5, timeout: float = 30.0):
        """Initialize connection pool"""
        self.db_path = db_path
        self.pool_size = pool_size
        self.timeout = timeout
        self.pool = Queue(maxsize=pool_size)
        self.all_connections = set()
        self.lock = threading.RLock()
        
        # Pre-populate pool with connections
        self._populate_pool()
    
    def _populate_pool(self):
        """Create initial connections for the pool"""
        with self.lock:
            for _ in range(self.pool_size):
                try:
                    conn = self._create_connection()
                    self.pool.put(conn, block=False)
                    self.all_connections.add(conn)
                except Full:
                    break
                except Exception as e:
                    logger.warning(f"Failed to create initial connection: {e}")
    
    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimized settings"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False  # Allow connection sharing between threads
        )
        
        # Optimize SQLite settings for better performance
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
        conn.execute("PRAGMA synchronous=NORMAL")  # Balance between safety and speed
        conn.execute("PRAGMA cache_size=10000")  # Increase cache size
        conn.execute("PRAGMA temp_store=MEMORY")  # Use memory for temporary tables
        
        return conn
    
    def get_connection(self, timeout: Optional[float] = None) -> sqlite3.Connection:
        """Get a connection from the pool with timeout"""
        timeout = timeout or self.timeout
        
        try:
            # Try to get a connection from pool
            conn = self.pool.get(timeout=timeout)
            
            # Test connection is still valid
            try:
                conn.execute("SELECT 1").fetchone()
                return conn
            except sqlite3.Error:
                # Connection is bad, create a new one
                logger.warning("Stale connection detected, creating new one")
                with self.lock:
                    self.all_connections.discard(conn)
                try:
                    conn.close()
                except:
                    pass
                
                # Create new connection
                new_conn = self._create_connection()
                with self.lock:
                    self.all_connections.add(new_conn)
                return new_conn
                
        except Empty:
            # Pool is empty, create temporary connection
            logger.warning(f"Connection pool exhausted, creating temporary connection")
            return self._create_connection()
    
    def return_connection(self, conn: sqlite3.Connection):
        """Return a connection to the pool"""
        if conn in self.all_connections:
            try:
                # Test connection before returning to pool
                conn.execute("SELECT 1").fetchone()
                self.pool.put(conn, block=False)
            except (sqlite3.Error, Full):
                # Connection is bad or pool is full, close it
                with self.lock:
                    self.all_connections.discard(conn)
                try:
                    conn.close()
                except:
                    pass
        else:
            # Temporary connection, just close it
            try:
                conn.close()
            except:
                pass
    
    def close_all(self):
        """Close all connections in the pool"""
        with self.lock:
            # Empty the pool queue
            while not self.pool.empty():
                try:
                    conn = self.pool.get_nowait()
                    conn.close()
                except (Empty, sqlite3.Error):
                    pass
            
            # Close any remaining connections
            for conn in list(self.all_connections):
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            
            self.all_connections.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics"""
        with self.lock:
            return {
                "pool_size": self.pool_size,
                "available_connections": self.pool.qsize(),
                "total_connections": len(self.all_connections),
                "timeout": self.timeout
            }


class DatabaseManager:
    """Centralized database manager for lifecycle MCP operations"""
    
    def __init__(self, db_path: Optional[str] = None, pool_size: int = 5, 
                 timeout: float = 30.0, enable_pooling: bool = True,
                 retry_attempts: int = 3, retry_delay: float = 0.1):
        """Initialize database manager with connection pooling"""
        self.db_path = db_path or os.environ.get("LIFECYCLE_DB", "lifecycle.db")
        self.pool_size = pool_size
        self.timeout = timeout
        self.enable_pooling = enable_pooling
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        
        # Initialize database and connection pool
        self._ensure_database_exists()
        
        if self.enable_pooling:
            self.connection_pool = ConnectionPool(
                self.db_path, 
                pool_size=pool_size, 
                timeout=timeout
            )
            logger.info(f"Database connection pool initialized: {pool_size} connections, {timeout}s timeout")
        else:
            self.connection_pool = None
            logger.info("Database connection pooling disabled")
    
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
        
        # Apply any pending migrations
        apply_all_migrations(self.db_path)
    
    @contextmanager
    def get_connection(self, row_factory: bool = False, timeout: Optional[float] = None):
        """Context manager for database connections with pooling and retry logic"""
        conn = None
        for attempt in range(self.retry_attempts):
            try:
                if self.enable_pooling and self.connection_pool:
                    conn = self.connection_pool.get_connection(timeout=timeout)
                else:
                    conn = sqlite3.connect(self.db_path, timeout=timeout or self.timeout)
                
                if row_factory:
                    conn.row_factory = sqlite3.Row
                
                yield conn
                return  # Success, exit retry loop
                
            except sqlite3.OperationalError as e:
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                
                # Check if this is a retry-able error
                if "database is locked" in str(e).lower() or "disk I/O error" in str(e).lower():
                    if attempt < self.retry_attempts - 1:
                        logger.warning(f"Database operation failed (attempt {attempt + 1}/{self.retry_attempts}): {e}")
                        time.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
                        continue
                
                logger.error(f"Database operation failed after {self.retry_attempts} attempts: {e}")
                raise
                
            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                logger.error(f"Database operation failed: {str(e)}")
                raise
                
            finally:
                if conn:
                    if self.enable_pooling and self.connection_pool:
                        self.connection_pool.return_connection(conn)
                    else:
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
    def transaction(self, row_factory: bool = False, timeout: Optional[float] = None):
        """Context manager for database transactions with pooling and retry logic"""
        conn = None
        for attempt in range(self.retry_attempts):
            try:
                if self.enable_pooling and self.connection_pool:
                    conn = self.connection_pool.get_connection(timeout=timeout)
                else:
                    conn = sqlite3.connect(self.db_path, timeout=timeout or self.timeout)
                
                if row_factory:
                    conn.row_factory = sqlite3.Row
                
                yield conn.cursor()
                conn.commit()
                return  # Success, exit retry loop
                
            except sqlite3.OperationalError as e:
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                
                # Check if this is a retry-able error
                if "database is locked" in str(e).lower() or "disk I/O error" in str(e).lower():
                    if attempt < self.retry_attempts - 1:
                        logger.warning(f"Transaction failed (attempt {attempt + 1}/{self.retry_attempts}): {e}")
                        time.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
                        continue
                
                logger.error(f"Transaction failed after {self.retry_attempts} attempts: {e}")
                raise
                
            except Exception as e:
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                logger.error(f"Transaction failed: {str(e)}")
                raise
                
            finally:
                if conn:
                    if self.enable_pooling and self.connection_pool:
                        self.connection_pool.return_connection(conn)
                    else:
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
    
    def configure_pool(self, pool_size: Optional[int] = None, timeout: Optional[float] = None, 
                      enable_pooling: Optional[bool] = None) -> Dict[str, Any]:
        """Reconfigure connection pool settings"""
        old_config = {
            "pool_size": self.pool_size,
            "timeout": self.timeout,
            "enable_pooling": self.enable_pooling
        }
        
        if pool_size is not None:
            self.pool_size = pool_size
        if timeout is not None:
            self.timeout = timeout
        if enable_pooling is not None:
            self.enable_pooling = enable_pooling
        
        # Reinitialize pool if settings changed
        if (pool_size is not None or timeout is not None or enable_pooling is not None):
            if self.connection_pool:
                self.connection_pool.close_all()
            
            if self.enable_pooling:
                self.connection_pool = ConnectionPool(
                    self.db_path, 
                    pool_size=self.pool_size, 
                    timeout=self.timeout
                )
                logger.info(f"Connection pool reconfigured: {self.pool_size} connections, {self.timeout}s timeout")
            else:
                self.connection_pool = None
                logger.info("Connection pooling disabled")
        
        return {
            "old_config": old_config,
            "new_config": {
                "pool_size": self.pool_size,
                "timeout": self.timeout,
                "enable_pooling": self.enable_pooling
            }
        }
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics and health metrics"""
        if not self.enable_pooling or not self.connection_pool:
            return {
                "pooling_enabled": False,
                "message": "Connection pooling is disabled"
            }
        
        pool_stats = self.connection_pool.get_stats()
        
        # Add additional metrics
        stats = {
            "pooling_enabled": True,
            "pool_health": "healthy" if pool_stats["available_connections"] > 0 else "depleted",
            **pool_stats,
            "retry_config": {
                "retry_attempts": self.retry_attempts,
                "retry_delay": self.retry_delay
            }
        }
        
        return stats
    
    def test_connection(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Test database connectivity and measure response time"""
        start_time = time.time()
        
        try:
            with self.get_connection(timeout=timeout) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1, datetime('now') as current_time")
                result = cursor.fetchone()
                
            end_time = time.time()
            response_time = (end_time - start_time) * 1000  # Convert to milliseconds
            
            return {
                "status": "success",
                "response_time_ms": round(response_time, 2),
                "database_time": result[1] if result else None,
                "pool_stats": self.get_pool_stats() if self.enable_pooling else None
            }
            
        except Exception as e:
            end_time = time.time()
            response_time = (end_time - start_time) * 1000
            
            return {
                "status": "failed",
                "error": str(e),
                "response_time_ms": round(response_time, 2),
                "pool_stats": self.get_pool_stats() if self.enable_pooling else None
            }
    
    def close(self):
        """Close all database connections and clean up resources"""
        if self.connection_pool:
            self.connection_pool.close_all()
            logger.info("Database connection pool closed")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup"""
        self.close()