#!/usr/bin/env python3
"""
Database migration utilities for MCP Lifecycle Management Server
Handles schema updates and data migrations
"""

import sqlite3


def apply_github_integration_migration(db_path: str) -> bool:
    """
    Apply migration to add GitHub integration fields to tasks table
    
    Args:
        db_path: Path to the SQLite database
        
    Returns:
        True if migration was applied successfully, False otherwise
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # First check if tasks table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        if not cursor.fetchone():
            print("Tasks table does not exist yet, skipping GitHub integration migration")
            return True
            
        # Check if github_issue_number column already exists
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'github_issue_number' not in columns:
            # Add GitHub integration columns
            cursor.execute("ALTER TABLE tasks ADD COLUMN github_issue_number TEXT")
            cursor.execute("ALTER TABLE tasks ADD COLUMN github_issue_url TEXT")
            
            conn.commit()
            print("GitHub integration migration applied successfully")
            return True
        else:
            print("GitHub integration migration already applied")
            return True
            
    except Exception as e:
        print(f"Error applying GitHub integration migration: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()


def get_schema_version(db_path: str) -> int:
    """Get the current schema version from the database"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if schema_version table exists
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='schema_version'
        """)
        
        if cursor.fetchone():
            cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            result = cursor.fetchone()
            return result[0] if result else 0
        else:
            # Create schema_version table
            cursor.execute("""
                CREATE TABLE schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)
            cursor.execute("INSERT INTO schema_version (version, description) VALUES (0, 'Initial schema')")
            conn.commit()
            return 0
            
    except Exception as e:
        print(f"Error getting schema version: {e}")
        return 0
    finally:
        if 'conn' in locals():
            conn.close()


def set_schema_version(db_path: str, version: int, description: str) -> bool:
    """Set the schema version in the database"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO schema_version (version, description) 
            VALUES (?, ?)
        """, (version, description))
        
        conn.commit()
        return True
        
    except Exception as e:
        print(f"Error setting schema version: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()


def apply_github_sync_metadata_migration(db_path: str) -> bool:
    """
    Apply migration to add GitHub sync metadata fields to tasks table
    
    Args:
        db_path: Path to the SQLite database
        
    Returns:
        True if migration was applied successfully, False otherwise
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # First check if tasks table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        if not cursor.fetchone():
            print("Tasks table does not exist yet, skipping GitHub sync metadata migration")
            return True
            
        # Check if github_etag column already exists
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'github_etag' not in columns:
            # Add GitHub sync metadata columns
            cursor.execute("ALTER TABLE tasks ADD COLUMN github_etag TEXT")
            cursor.execute("ALTER TABLE tasks ADD COLUMN github_last_sync TEXT")
            
            conn.commit()
            print("GitHub sync metadata migration applied successfully")
            return True
        else:
            print("GitHub sync metadata migration already applied")
            return True
            
    except Exception as e:
        print(f"Error applying GitHub sync metadata migration: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()


def apply_all_migrations(db_path: str) -> bool:
    """Apply all pending migrations to the database"""
    current_version = get_schema_version(db_path)
    
    migrations = [
        (1, "GitHub integration fields", apply_github_integration_migration),
        (2, "GitHub sync metadata fields", apply_github_sync_metadata_migration)
    ]
    
    for version, description, migration_func in migrations:
        if current_version < version:
            print(f"Applying migration {version}: {description}")
            if migration_func(db_path):
                set_schema_version(db_path, version, description)
                current_version = version
            else:
                print(f"Migration {version} failed")
                return False
    
    return True