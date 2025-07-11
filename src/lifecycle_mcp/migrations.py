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

        # Check if github_issue_number column already exists
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in cursor.fetchall()]

        if "github_issue_number" not in columns:
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
        if "conn" in locals():
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
        if "conn" in locals():
            conn.close()


def set_schema_version(db_path: str, version: int, description: str) -> bool:
    """Set the schema version in the database"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO schema_version (version, description) 
            VALUES (?, ?)
        """,
            (version, description),
        )

        conn.commit()
        return True

    except Exception as e:
        print(f"Error setting schema version: {e}")
        return False
    finally:
        if "conn" in locals():
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

        # Check if github_etag column already exists
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in cursor.fetchall()]

        if "github_etag" not in columns:
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
        if "conn" in locals():
            conn.close()


def apply_decomposition_extension_migration(db_path: str) -> bool:
    """
    Apply migration to add requirement decomposition extensions

    Args:
        db_path: Path to the SQLite database

    Returns:
        True if migration was applied successfully, False otherwise
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if decomposition_metadata column already exists
        cursor.execute("PRAGMA table_info(requirements)")
        columns = [column[1] for column in cursor.fetchall()]

        if "decomposition_metadata" not in columns:
            # Add decomposition-specific metadata to requirements table
            # JSON for LLM analysis results
            cursor.execute("ALTER TABLE requirements ADD COLUMN decomposition_metadata TEXT")
            cursor.execute(
                "ALTER TABLE requirements ADD COLUMN decomposition_source TEXT "
                "CHECK (decomposition_source IN "
                "('manual', 'llm_automatic', 'llm_suggested'))"
            )
            cursor.execute(
                "ALTER TABLE requirements ADD COLUMN complexity_score INTEGER CHECK (complexity_score BETWEEN 1 AND 10)"
            )
            cursor.execute(
                "ALTER TABLE requirements ADD COLUMN scope_assessment TEXT "
                "CHECK (scope_assessment IN "
                "('single_feature', 'multiple_features', 'complex_workflow', 'epic'))"
            )
            # Max 3 levels
            cursor.execute(
                "ALTER TABLE requirements ADD COLUMN decomposition_level INTEGER "
                "DEFAULT 0 CHECK (decomposition_level BETWEEN 0 AND 3)"
            )

            # Create requirement hierarchy view
            cursor.execute("""
            CREATE VIEW IF NOT EXISTS requirement_hierarchy AS
            WITH RECURSIVE requirement_tree AS (
                -- Base case: top-level requirements (no parent)
                SELECT
                    r.id,
                    r.title,
                    r.status,
                    r.priority,
                    r.decomposition_level,
                    r.complexity_score,
                    r.scope_assessment,
                    NULL as parent_requirement_id,
                    0 as hierarchy_level,
                    r.id as root_requirement_id,
                    r.type || '-' || CAST(r.requirement_number AS TEXT) as path
                FROM requirements r
                WHERE r.id NOT IN (
                    SELECT rd.requirement_id
                    FROM requirement_dependencies rd
                    WHERE rd.dependency_type = 'parent'
                )

                UNION ALL

                -- Recursive case: child requirements
                SELECT
                    r.id,
                    r.title,
                    r.status,
                    r.priority,
                    r.decomposition_level,
                    r.complexity_score,
                    r.scope_assessment,
                    rd.depends_on_requirement_id as parent_requirement_id,
                    rt.hierarchy_level + 1,
                    rt.root_requirement_id,
                    rt.path || ' > ' || r.type || '-' || 
                    CAST(r.requirement_number AS TEXT)
                FROM requirements r
                JOIN requirement_dependencies rd ON r.id = rd.requirement_id
                JOIN requirement_tree rt ON rd.depends_on_requirement_id = rt.id
                WHERE rd.dependency_type = 'parent' AND rt.hierarchy_level < 3
            )
            SELECT * FROM requirement_tree
            """)

            # Create decomposition candidates view
            cursor.execute("""
            CREATE VIEW IF NOT EXISTS decomposition_candidates AS
            SELECT
                r.id,
                r.title,
                r.status,
                r.complexity_score,
                r.scope_assessment,
                r.decomposition_level,
                (LENGTH(r.functional_requirements) - 
                 LENGTH(REPLACE(r.functional_requirements, ',', '')) + 1) 
                 as functional_req_count,
                (LENGTH(r.acceptance_criteria) - 
                 LENGTH(REPLACE(r.acceptance_criteria, ',', '')) + 1) 
                 as acceptance_criteria_count,
                CASE
                    WHEN r.complexity_score >= 7 THEN 'High'
                    WHEN r.complexity_score >= 5 THEN 'Medium'
                    ELSE 'Low'
                END as decomposition_priority
            FROM requirements r
            WHERE r.status IN ('Draft', 'Under Review')
                AND r.decomposition_level < 3
                AND (
                    r.complexity_score >= 5
                    OR r.scope_assessment IN 
                    ('multiple_features', 'complex_workflow', 'epic')
                    OR (LENGTH(r.functional_requirements) - 
                        LENGTH(REPLACE(r.functional_requirements, ',', '')) + 1) > 5
                )
            """)

            # Add indexes for decomposition queries
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_requirement_dependencies_parent "
                "ON requirement_dependencies(depends_on_requirement_id, dependency_type)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_requirements_decomposition "
                "ON requirements(decomposition_level, complexity_score, scope_assessment)"
            )

            # Add triggers for decomposition validation
            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS validate_decomposition_level
            BEFORE INSERT ON requirement_dependencies
            WHEN NEW.dependency_type = 'parent'
            BEGIN
                SELECT CASE
                    WHEN (
                        SELECT decomposition_level
                        FROM requirements
                        WHERE id = NEW.depends_on_requirement_id
                    ) >= 3
                    THEN RAISE(ABORT, 'Maximum decomposition depth of 3 levels exceeded')
                END;
            END
            """)

            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS set_decomposition_level
            AFTER INSERT ON requirement_dependencies
            WHEN NEW.dependency_type = 'parent'
            BEGIN
                UPDATE requirements
                SET decomposition_level = (
                    SELECT COALESCE(parent_req.decomposition_level, 0) + 1
                    FROM requirements parent_req
                    WHERE parent_req.id = NEW.depends_on_requirement_id
                )
                WHERE id = NEW.requirement_id;
            END
            """)

            cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_circular_dependencies
            BEFORE INSERT ON requirement_dependencies
            WHEN NEW.dependency_type = 'parent'
            BEGIN
                SELECT CASE
                    WHEN EXISTS (
                        WITH RECURSIVE circular_check AS (
                            SELECT NEW.depends_on_requirement_id as ancestor_id
                            UNION ALL
                            SELECT rd.depends_on_requirement_id
                            FROM requirement_dependencies rd
                            JOIN circular_check cc ON rd.requirement_id = cc.ancestor_id
                            WHERE rd.dependency_type = 'parent'
                        )
                        SELECT 1 FROM circular_check 
                        WHERE ancestor_id = NEW.requirement_id
                    )
                    THEN RAISE(ABORT, 'Circular dependency detected in parent-child relationship')
                END;
            END
            """)

            conn.commit()
            print("Decomposition extension migration applied successfully")
            return True
        else:
            print("Decomposition extension migration already applied")
            return True

    except Exception as e:
        print(f"Error applying decomposition extension migration: {e}")
        return False
    finally:
        if "conn" in locals():
            conn.close()


def apply_all_migrations(db_path: str) -> bool:
    """Apply all pending migrations to the database"""
    current_version = get_schema_version(db_path)

    migrations = [
        (1, "GitHub integration fields", apply_github_integration_migration),
        (2, "GitHub sync metadata fields", apply_github_sync_metadata_migration),
        (3, "Requirement decomposition extension", apply_decomposition_extension_migration),
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
