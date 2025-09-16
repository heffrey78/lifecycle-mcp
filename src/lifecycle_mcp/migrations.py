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


def fix_blocked_items_view_migration(db_path: str) -> bool:
    """
    Apply migration to fix blocked_items view column reference

    Args:
        db_path: Path to the SQLite database

    Returns:
        True if migration was applied successfully, False otherwise
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Drop and recreate the blocked_items view with correct column reference
        cursor.execute("DROP VIEW IF EXISTS blocked_items")
        cursor.execute("""
            CREATE VIEW blocked_items AS
            SELECT
                'task' as item_type,
                t.id,
                t.title,
                t.status,
                GROUP_CONCAT(td.depends_on_task_id) as blocking_items
            FROM tasks t
            JOIN task_dependencies td ON t.id = td.task_id
            JOIN tasks dt ON td.depends_on_task_id = dt.id
            WHERE t.status = 'Blocked' OR (t.status = 'Not Started' AND dt.status != 'Complete')
            GROUP BY t.id

            UNION ALL

            SELECT
                'requirement' as item_type,
                r.id,
                r.title,
                r.status,
                GROUP_CONCAT(rd.depends_on_requirement_id) as blocking_items
            FROM requirements r
            JOIN requirement_dependencies rd ON r.id = rd.requirement_id
            JOIN requirements dr ON rd.depends_on_requirement_id = dr.id
            WHERE dr.status NOT IN ('Validated', 'Deprecated')
            GROUP BY r.id
        """)

        conn.commit()
        print("Blocked items view migration applied successfully")
        return True

    except Exception as e:
        print(f"Error applying blocked items view migration: {e}")
        return False
    finally:
        if "conn" in locals():
            conn.close()


def apply_relationship_schema_migration(db_path: str) -> bool:
    """
    Apply migration to create unified polymorphic relationships table

    Args:
        db_path: Path to the SQLite database

    Returns:
        True if migration was applied successfully, False otherwise
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if relationships table already exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='relationships'")

        if not cursor.fetchone():
            # Create unified polymorphic relationships table
            cursor.execute("""
                CREATE TABLE relationships (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL CHECK (source_type IN ('requirement', 'task', 'architecture')),
                    source_id TEXT NOT NULL,
                    target_type TEXT NOT NULL CHECK (target_type IN ('requirement', 'task', 'architecture')),
                    target_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL CHECK (relationship_type IN ('implements', 'addresses', 'depends', 'blocks', 'informs', 'requires', 'parent', 'refines', 'conflicts', 'relates')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_type, source_id, target_type, target_id, relationship_type)
                )
            """)

            # Add performance indexes
            cursor.execute("CREATE INDEX idx_relationships_source ON relationships(source_type, source_id)")
            cursor.execute("CREATE INDEX idx_relationships_target ON relationships(target_type, target_id)")
            cursor.execute("CREATE INDEX idx_relationships_type ON relationships(relationship_type)")

            conn.commit()
            print("Relationship schema migration applied successfully")

            # Validate table creation
            cursor.execute("PRAGMA table_info(relationships)")
            table_info = cursor.fetchall()
            expected_columns = ['id', 'source_type', 'source_id', 'target_type', 'target_id', 'relationship_type', 'created_at']
            actual_columns = [column[1] for column in table_info]

            for expected_col in expected_columns:
                if expected_col not in actual_columns:
                    raise Exception(f"Expected column '{expected_col}' not found in relationships table")

            return True
        else:
            print("Relationship schema migration already applied")
            return True

    except Exception as e:
        print(f"Error applying relationship schema migration: {e}")
        if "conn" in locals():
            conn.rollback()
        return False
    finally:
        if "conn" in locals():
            conn.close()


def apply_relationship_consolidation_migration(db_path: str) -> bool:
    """
    Apply migration to consolidate existing relationship data into unified table

    Args:
        db_path: Path to the SQLite database

    Returns:
        True if migration was applied successfully, False otherwise
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if consolidation already applied by looking for migrated data
        cursor.execute("SELECT COUNT(*) FROM relationships")
        existing_relationships = cursor.fetchone()[0]

        if existing_relationships > 0:
            print("Relationship consolidation migration already applied")
            return True

        print("Starting relationship data consolidation...")

        # 1. Migrate parent_task_id relationships from tasks table
        cursor.execute("""
            SELECT id, parent_task_id, title
            FROM tasks
            WHERE parent_task_id IS NOT NULL AND parent_task_id != ''
        """)
        parent_relationships = cursor.fetchall()

        for task_id, parent_task_id, title in parent_relationships:
            relationship_id = f"rel-{task_id}-{parent_task_id}-parent"
            cursor.execute("""
                INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type)
                VALUES (?, 'task', ?, 'task', ?, 'parent')
            """, (relationship_id, task_id, parent_task_id))
            print(f"Migrated parent relationship: {task_id} → {parent_task_id}")

        # 2. Migrate requirement_tasks junction table data
        cursor.execute("""
            SELECT requirement_id, task_id, created_at
            FROM requirement_tasks
        """)
        requirement_task_relationships = cursor.fetchall()

        for req_id, task_id, created_at in requirement_task_relationships:
            relationship_id = f"rel-{req_id}-{task_id}-implements"
            cursor.execute("""
                INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type, created_at)
                VALUES (?, 'requirement', ?, 'task', ?, 'implements', ?)
            """, (relationship_id, req_id, task_id, created_at))
            print(f"Migrated requirement→task relationship: {req_id} → {task_id}")

        # 3. Migrate requirement_architecture junction table data (if any)
        cursor.execute("""
            SELECT requirement_id, architecture_id, relationship_type
            FROM requirement_architecture
        """)
        req_arch_relationships = cursor.fetchall()

        for req_id, arch_id, rel_type in req_arch_relationships:
            # Default to 'addresses' if relationship_type is None or empty
            if not rel_type:
                rel_type = 'addresses'
            relationship_id = f"rel-{req_id}-{arch_id}-{rel_type}"
            cursor.execute("""
                INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type)
                VALUES (?, 'requirement', ?, 'architecture', ?, ?)
            """, (relationship_id, req_id, arch_id, rel_type))
            print(f"Migrated requirement→architecture relationship: {req_id} → {arch_id} ({rel_type})")

        # 4. Migrate task_dependencies table data (if any)
        cursor.execute("""
            SELECT task_id, depends_on_task_id, dependency_type
            FROM task_dependencies
        """)
        task_deps = cursor.fetchall()

        for task_id, depends_on_task_id, dep_type in task_deps:
            # Default to 'depends' if dependency_type is None or empty
            if not dep_type:
                dep_type = 'depends'
            relationship_id = f"rel-{task_id}-{depends_on_task_id}-{dep_type}"
            cursor.execute("""
                INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type)
                VALUES (?, 'task', ?, 'task', ?, ?)
            """, (relationship_id, task_id, depends_on_task_id, dep_type))
            print(f"Migrated task dependency: {task_id} → {depends_on_task_id} ({dep_type})")

        # 5. Migrate requirement_dependencies table data (if any)
        cursor.execute("""
            SELECT requirement_id, depends_on_requirement_id, dependency_type
            FROM requirement_dependencies
        """)
        req_deps = cursor.fetchall()

        for req_id, depends_on_req_id, dep_type in req_deps:
            # Default to 'depends' if dependency_type is None or empty
            if not dep_type:
                dep_type = 'depends'
            relationship_id = f"rel-{req_id}-{depends_on_req_id}-{dep_type}"
            cursor.execute("""
                INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type)
                VALUES (?, 'requirement', ?, 'requirement', ?, ?)
            """, (relationship_id, req_id, depends_on_req_id, dep_type))
            print(f"Migrated requirement dependency: {req_id} → {depends_on_req_id} ({dep_type})")

        conn.commit()

        # Verify migration success
        cursor.execute("SELECT COUNT(*) FROM relationships")
        final_count = cursor.fetchone()[0]

        total_migrated = len(parent_relationships) + len(requirement_task_relationships) + len(req_arch_relationships) + len(task_deps) + len(req_deps)

        if final_count != total_migrated:
            raise Exception(f"Migration verification failed: expected {total_migrated} relationships, found {final_count}")

        print(f"Relationship consolidation migration completed successfully: {final_count} relationships migrated")
        return True

    except Exception as e:
        print(f"Error applying relationship consolidation migration: {e}")
        if "conn" in locals():
            conn.rollback()
        return False
    finally:
        if "conn" in locals():
            conn.close()


def apply_relationship_cleanup_migration(db_path: str) -> bool:
    """
    Remove redundant relationship tables and columns after data consolidation.
    Schema Version 7: Cleanup phase
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("Starting relationship table cleanup migration...")

        # Check if cleanup already applied by checking if any tables exist
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('task_dependencies', 'requirement_dependencies', 'requirement_architecture')
        """)
        existing_tables = [row[0] for row in cursor.fetchall()]

        # Also check if parent_task_id column exists
        cursor.execute("PRAGMA table_info(tasks)")
        columns_info_check = cursor.fetchall()
        has_parent_task_id_check = any(col[1] == 'parent_task_id' for col in columns_info_check)

        if not existing_tables and not has_parent_task_id_check:
            print("Relationship cleanup migration already applied")
            return True

        print(f"Found {len(existing_tables)} tables to clean up: {existing_tables}")
        if has_parent_task_id_check:
            print("parent_task_id column needs to be removed")

        # Verify data has been migrated to relationships table
        cursor.execute("SELECT COUNT(*) FROM relationships")
        relationship_count = cursor.fetchone()[0]

        if relationship_count == 0:
            raise Exception("Cannot cleanup: no relationships found in unified table. Data consolidation may not have completed.")

        print(f"Found {relationship_count} relationships in unified table, proceeding with cleanup...")

        # 1. Drop task_dependencies table (verify data migrated to unified table)
        if 'task_dependencies' in existing_tables:
            cursor.execute("SELECT COUNT(*) FROM task_dependencies")
            old_count = cursor.fetchone()[0]

            if old_count > 0:
                # Verify that all old relationships exist in new table
                cursor.execute("""
                    SELECT COUNT(*) FROM task_dependencies td
                    WHERE NOT EXISTS (
                        SELECT 1 FROM relationships r
                        WHERE r.source_type = 'task'
                        AND r.source_id = td.task_id
                        AND r.target_type = 'task'
                        AND r.target_id = td.depends_on_task_id
                        AND r.relationship_type = COALESCE(td.dependency_type, 'depends')
                    )
                """)
                unmigrated_count = cursor.fetchone()[0]

                if unmigrated_count > 0:
                    raise Exception(f"Cannot drop task_dependencies: {unmigrated_count} relationships not found in unified table. Data consolidation incomplete.")

                print(f"Verified {old_count} task dependencies migrated to unified table")

            cursor.execute("DROP TABLE task_dependencies")
            print("Dropped task_dependencies table")

        # 2. Drop requirement_dependencies table (verify data migrated to unified table)
        if 'requirement_dependencies' in existing_tables:
            cursor.execute("SELECT COUNT(*) FROM requirement_dependencies")
            old_count = cursor.fetchone()[0]

            if old_count > 0:
                # Verify that all old relationships exist in new table
                cursor.execute("""
                    SELECT COUNT(*) FROM requirement_dependencies rd
                    WHERE NOT EXISTS (
                        SELECT 1 FROM relationships r
                        WHERE r.source_type = 'requirement'
                        AND r.source_id = rd.requirement_id
                        AND r.target_type = 'requirement'
                        AND r.target_id = rd.depends_on_requirement_id
                        AND r.relationship_type = COALESCE(rd.dependency_type, 'depends')
                    )
                """)
                unmigrated_count = cursor.fetchone()[0]

                if unmigrated_count > 0:
                    raise Exception(f"Cannot drop requirement_dependencies: {unmigrated_count} relationships not found in unified table. Data consolidation incomplete.")

                print(f"Verified {old_count} requirement dependencies migrated to unified table")

            cursor.execute("DROP TABLE requirement_dependencies")
            print("Dropped requirement_dependencies table")

        # 3. Drop requirement_architecture table (verify data migrated to unified table)
        if 'requirement_architecture' in existing_tables:
            cursor.execute("SELECT COUNT(*) FROM requirement_architecture")
            old_count = cursor.fetchone()[0]

            if old_count > 0:
                # Verify that all old relationships exist in new table
                cursor.execute("""
                    SELECT COUNT(*) FROM requirement_architecture ra
                    WHERE NOT EXISTS (
                        SELECT 1 FROM relationships r
                        WHERE r.source_type = 'requirement'
                        AND r.source_id = ra.requirement_id
                        AND r.target_type = 'architecture'
                        AND r.target_id = ra.architecture_id
                        AND r.relationship_type = COALESCE(ra.relationship_type, 'addresses')
                    )
                """)
                unmigrated_count = cursor.fetchone()[0]

                if unmigrated_count > 0:
                    raise Exception(f"Cannot drop requirement_architecture: {unmigrated_count} relationships not found in unified table. Data consolidation incomplete.")

                print(f"Verified {old_count} requirement->architecture relationships migrated to unified table")

            cursor.execute("DROP TABLE requirement_architecture")
            print("Dropped requirement_architecture table")

        # 4. Remove parent_task_id column from tasks table
        # SQLite doesn't support DROP COLUMN, so we need to recreate the table
        cursor.execute("PRAGMA table_info(tasks)")
        columns_info = cursor.fetchall()

        # Check if parent_task_id column exists
        has_parent_task_id = any(col[1] == 'parent_task_id' for col in columns_info)

        if has_parent_task_id:
            # Verify parent relationships were migrated to unified table
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE parent_task_id IS NOT NULL AND parent_task_id != ''")
            parent_count = cursor.fetchone()[0]

            if parent_count > 0:
                # Verify that all parent relationships exist in new table
                cursor.execute("""
                    SELECT COUNT(*) FROM tasks t
                    WHERE t.parent_task_id IS NOT NULL AND t.parent_task_id != ''
                    AND NOT EXISTS (
                        SELECT 1 FROM relationships r
                        WHERE r.source_type = 'task'
                        AND r.source_id = t.id
                        AND r.target_type = 'task'
                        AND r.target_id = t.parent_task_id
                        AND r.relationship_type = 'parent'
                    )
                """)
                unmigrated_count = cursor.fetchone()[0]

                if unmigrated_count > 0:
                    raise Exception(f"Cannot remove parent_task_id: {unmigrated_count} parent relationships not found in unified table. Data consolidation incomplete.")

                print(f"Verified {parent_count} parent task relationships migrated to unified table")

            # Get all columns except parent_task_id
            columns_to_keep = [col[1] for col in columns_info if col[1] != 'parent_task_id']
            columns_str = ', '.join(columns_to_keep)

            # Create new tasks table without parent_task_id
            cursor.execute(f"""
                CREATE TABLE tasks_new AS
                SELECT {columns_str} FROM tasks
            """)

            # Drop old table and rename new one
            cursor.execute("DROP TABLE tasks")
            cursor.execute("ALTER TABLE tasks_new RENAME TO tasks")

            # Recreate indexes and triggers for tasks table
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee)")

            # Recreate update trigger
            cursor.execute("""
                CREATE TRIGGER update_task_timestamp
                AFTER UPDATE ON tasks
                BEGIN
                    UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
                END
            """)

            # Recreate status change trigger
            cursor.execute("""
                CREATE TRIGGER log_task_status_change
                AFTER UPDATE OF status ON tasks
                WHEN OLD.status != NEW.status
                BEGIN
                    INSERT INTO lifecycle_events (entity_type, entity_id, event_type, from_value, to_value)
                    VALUES ('task', NEW.id, 'status_change', OLD.status, NEW.status);

                    -- Update completed timestamp
                    UPDATE tasks
                    SET completed_at = CASE
                        WHEN NEW.status = 'Complete' THEN CURRENT_TIMESTAMP
                        ELSE NULL
                    END
                    WHERE id = NEW.id;
                END
            """)

            print("Removed parent_task_id column from tasks table")

        # 5. Update requirement task completion trigger to use new relationships table
        cursor.execute("DROP TRIGGER IF EXISTS update_requirement_task_completion")
        cursor.execute("""
            CREATE TRIGGER update_requirement_task_completion
            AFTER UPDATE OF status ON tasks
            WHEN NEW.status = 'Complete' OR OLD.status = 'Complete'
            BEGIN
                UPDATE requirements
                SET tasks_completed = (
                    SELECT COUNT(*)
                    FROM relationships r
                    JOIN tasks t ON r.target_id = t.id
                    WHERE r.source_id = requirements.id
                    AND r.source_type = 'requirement'
                    AND r.target_type = 'task'
                    AND r.relationship_type = 'implements'
                    AND t.status = 'Complete'
                )
                WHERE id IN (
                    SELECT source_id FROM relationships
                    WHERE target_id = NEW.id
                    AND source_type = 'requirement'
                    AND target_type = 'task'
                    AND relationship_type = 'implements'
                );
            END
        """)
        print("Updated requirement task completion trigger for unified relationships table")

        # 6. Update requirement task count trigger to use new relationships table
        cursor.execute("DROP TRIGGER IF EXISTS update_requirement_task_count_insert")
        cursor.execute("""
            CREATE TRIGGER update_requirement_task_count_insert
            AFTER INSERT ON relationships
            WHEN NEW.source_type = 'requirement' AND NEW.target_type = 'task' AND NEW.relationship_type = 'implements'
            BEGIN
                UPDATE requirements
                SET task_count = (
                    SELECT COUNT(*) FROM relationships
                    WHERE source_id = NEW.source_id
                    AND source_type = 'requirement'
                    AND target_type = 'task'
                    AND relationship_type = 'implements'
                )
                WHERE id = NEW.source_id;
            END
        """)
        print("Updated requirement task count trigger for unified relationships table")

        # 7. Update requirement_progress view to use new relationships table
        cursor.execute("DROP VIEW IF EXISTS requirement_progress")
        cursor.execute("""
            CREATE VIEW requirement_progress AS
            SELECT
                r.id,
                r.title,
                r.status,
                r.priority,
                r.task_count,
                r.tasks_completed,
                CASE
                    WHEN r.task_count = 0 THEN 0
                    ELSE ROUND(CAST(r.tasks_completed AS FLOAT) / r.task_count * 100, 2)
                END as completion_percentage,
                COUNT(DISTINCT rel.target_id) as architecture_artifacts
            FROM requirements r
            LEFT JOIN relationships rel ON r.id = rel.source_id
                AND rel.source_type = 'requirement'
                AND rel.target_type = 'architecture'
            WHERE r.status != 'Deprecated'
            GROUP BY r.id
        """)
        print("Updated requirement_progress view for unified relationships table")

        # 8. Update requirement_hierarchy view to use new relationships table
        cursor.execute("DROP VIEW IF EXISTS requirement_hierarchy")
        cursor.execute("""
            CREATE VIEW requirement_hierarchy AS
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
                    SELECT rel.source_id
                    FROM relationships rel
                    WHERE rel.source_type = 'requirement'
                    AND rel.target_type = 'requirement'
                    AND rel.relationship_type = 'parent'
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
                    rel.target_id as parent_requirement_id,
                    rt.hierarchy_level + 1,
                    rt.root_requirement_id,
                    rt.path || ' > ' || r.type || '-' ||
                    CAST(r.requirement_number AS TEXT)
                FROM requirements r
                JOIN relationships rel ON r.id = rel.source_id
                JOIN requirement_tree rt ON rel.target_id = rt.id
                WHERE rel.source_type = 'requirement'
                AND rel.target_type = 'requirement'
                AND rel.relationship_type = 'parent'
                AND rt.hierarchy_level < 3
            )
            SELECT * FROM requirement_tree
        """)
        print("Updated requirement_hierarchy view for unified relationships table")

        # 9. Update blocked_items view to use new relationships table
        cursor.execute("DROP VIEW IF EXISTS blocked_items")
        cursor.execute("""
            CREATE VIEW blocked_items AS
            SELECT
                'task' as item_type,
                t.id,
                t.title,
                t.status,
                GROUP_CONCAT(rel.target_id) as blocking_items
            FROM tasks t
            JOIN relationships rel ON t.id = rel.source_id
            JOIN tasks dt ON rel.target_id = dt.id
            WHERE rel.source_type = 'task'
            AND rel.target_type = 'task'
            AND rel.relationship_type IN ('depends', 'blocks')
            AND (t.status = 'Blocked' OR (t.status = 'Not Started' AND dt.status != 'Complete'))
            GROUP BY t.id

            UNION ALL

            SELECT
                'requirement' as item_type,
                r.id,
                r.title,
                r.status,
                GROUP_CONCAT(rel.target_id) as blocking_items
            FROM requirements r
            JOIN relationships rel ON r.id = rel.source_id
            JOIN requirements dr ON rel.target_id = dr.id
            WHERE rel.source_type = 'requirement'
            AND rel.target_type = 'requirement'
            AND rel.relationship_type IN ('depends', 'blocks')
            AND dr.status NOT IN ('Validated', 'Deprecated')
            GROUP BY r.id
        """)
        print("Updated blocked_items view for unified relationships table")

        conn.commit()

        # Verify cleanup success
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('task_dependencies', 'requirement_dependencies', 'requirement_architecture')
        """)
        remaining_tables = cursor.fetchall()

        if remaining_tables:
            raise Exception(f"Cleanup verification failed: tables still exist: {[t[0] for t in remaining_tables]}")

        # Verify parent_task_id column removed
        cursor.execute("PRAGMA table_info(tasks)")
        columns_after = cursor.fetchall()
        if any(col[1] == 'parent_task_id' for col in columns_after):
            raise Exception("Cleanup verification failed: parent_task_id column still exists in tasks table")

        print(f"Relationship cleanup migration completed successfully")
        return True

    except Exception as e:
        print(f"Error applying relationship cleanup migration: {e}")
        if "conn" in locals():
            conn.rollback()
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
        (4, "Fix blocked_items view column reference", fix_blocked_items_view_migration),
        (5, "Create unified relationships table", apply_relationship_schema_migration),
        (6, "Consolidate relationship data", apply_relationship_consolidation_migration),
        (7, "Remove redundant relationship tables", apply_relationship_cleanup_migration),
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
