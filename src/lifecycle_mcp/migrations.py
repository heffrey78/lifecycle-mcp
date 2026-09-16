#!/usr/bin/env python3
"""
Database migrations for the Lifecycle MCP server.

A new database is created from lifecycle-schema.sql (the version 0 baseline) and then brought up
to date by the same migrations an existing database runs, so every database follows one path.

Each pending migration runs inside a single transaction together with its schema_version row.
SQLite DDL is transactional, so a failing migration leaves no partial schema behind; the runner
then raises MigrationError and the server refuses to start instead of running on a broken schema.
"""

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

Migration = Callable[[sqlite3.Connection], None]


class MigrationError(RuntimeError):
    """A migration failed and was rolled back; the database stays at its previous version."""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# --- migrations 1-7 ----------------------------------------------------------------------------


def add_github_integration_columns(conn: sqlite3.Connection) -> None:
    if "github_issue_number" not in _columns(conn, "tasks"):
        conn.execute("ALTER TABLE tasks ADD COLUMN github_issue_number TEXT")
        conn.execute("ALTER TABLE tasks ADD COLUMN github_issue_url TEXT")


def add_github_sync_metadata_columns(conn: sqlite3.Connection) -> None:
    if "github_etag" not in _columns(conn, "tasks"):
        conn.execute("ALTER TABLE tasks ADD COLUMN github_etag TEXT")
        conn.execute("ALTER TABLE tasks ADD COLUMN github_last_sync TEXT")


def add_decomposition_columns(conn: sqlite3.Connection) -> None:
    """Requirement decomposition metadata. Its link-based view and triggers live in migration 8."""
    if "decomposition_metadata" in _columns(conn, "requirements"):
        return
    conn.execute("ALTER TABLE requirements ADD COLUMN decomposition_metadata TEXT")
    conn.execute(
        "ALTER TABLE requirements ADD COLUMN decomposition_source TEXT "
        "CHECK (decomposition_source IN ('manual', 'llm_automatic', 'llm_suggested'))"
    )
    conn.execute(
        "ALTER TABLE requirements ADD COLUMN complexity_score INTEGER CHECK (complexity_score BETWEEN 1 AND 10)"
    )
    conn.execute(
        "ALTER TABLE requirements ADD COLUMN scope_assessment TEXT "
        "CHECK (scope_assessment IN ('single_feature', 'multiple_features', 'complex_workflow', 'epic'))"
    )
    conn.execute(
        "ALTER TABLE requirements ADD COLUMN decomposition_level INTEGER "
        "DEFAULT 0 CHECK (decomposition_level BETWEEN 0 AND 3)"
    )
    conn.execute("""
        CREATE VIEW IF NOT EXISTS decomposition_candidates AS
        SELECT
            r.id,
            r.title,
            r.status,
            r.complexity_score,
            r.scope_assessment,
            r.decomposition_level,
            (LENGTH(r.functional_requirements) - LENGTH(REPLACE(r.functional_requirements, ',', '')) + 1)
                AS functional_req_count,
            (LENGTH(r.acceptance_criteria) - LENGTH(REPLACE(r.acceptance_criteria, ',', '')) + 1)
                AS acceptance_criteria_count,
            CASE
                WHEN r.complexity_score >= 7 THEN 'High'
                WHEN r.complexity_score >= 5 THEN 'Medium'
                ELSE 'Low'
            END AS decomposition_priority
        FROM requirements r
        WHERE r.status IN ('Draft', 'Under Review')
            AND r.decomposition_level < 3
            AND (
                r.complexity_score >= 5
                OR r.scope_assessment IN ('multiple_features', 'complex_workflow', 'epic')
                OR (LENGTH(r.functional_requirements) - LENGTH(REPLACE(r.functional_requirements, ',', '')) + 1) > 5
            )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requirements_decomposition "
        "ON requirements(decomposition_level, complexity_score, scope_assessment)"
    )


def create_relationships_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL CHECK (source_type IN ('requirement', 'task', 'architecture')),
            source_id TEXT NOT NULL,
            target_type TEXT NOT NULL CHECK (target_type IN ('requirement', 'task', 'architecture')),
            target_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL CHECK (relationship_type IN (
                'implements', 'addresses', 'depends', 'blocks', 'informs',
                'requires', 'parent', 'refines', 'conflicts', 'relates'
            )),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_type, source_id, target_type, target_id, relationship_type)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_type, source_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_type, target_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type)")


def superseded(conn: sqlite3.Connection) -> None:
    """Replaced by migration 8. Kept so version numbers stay stable for existing databases."""


# --- migration 8: one link store ---------------------------------------------------------------

LEGACY_LINK_TABLES = ("requirement_tasks", "requirement_architecture", "task_dependencies", "requirement_dependencies")

LINK_VIEWS = ("requirement_progress", "task_hierarchy", "blocked_items", "requirement_hierarchy")

LINK_TRIGGERS = (
    "update_requirement_task_count_insert",
    "update_requirement_task_count_delete",
    "update_requirement_task_completion",
    "validate_decomposition_level",
    "set_decomposition_level",
    "prevent_circular_dependencies",
)

_INSERT_LINK = (
    "INSERT OR IGNORE INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type"
)

# Legacy table -> statements copying its rows into relationships. Requirement links always point
# requirement -> task/architecture; task and requirement dependencies point dependent -> dependency,
# except "blocks", which points blocker -> blocked as create_relationship defines it.
LEGACY_LINK_COPIES = {
    "requirement_tasks": [
        f"""{_INSERT_LINK}, created_at)
            SELECT 'rel-' || requirement_id || '-' || task_id || '-implements', 'requirement', requirement_id,
                   'task', task_id, 'implements', COALESCE(created_at, CURRENT_TIMESTAMP)
            FROM requirement_tasks""",
    ],
    "requirement_architecture": [
        f"""{_INSERT_LINK})
            SELECT 'rel-' || requirement_id || '-' || architecture_id || '-addresses', 'requirement', requirement_id,
                   'architecture', architecture_id, 'addresses'
            FROM requirement_architecture""",
    ],
    "task_dependencies": [
        f"""{_INSERT_LINK})
            SELECT 'rel-' || depends_on_task_id || '-' || task_id || '-blocks', 'task', depends_on_task_id,
                   'task', task_id, 'blocks'
            FROM task_dependencies WHERE dependency_type = 'blocks'""",
        f"""{_INSERT_LINK})
            SELECT 'rel-' || task_id || '-' || depends_on_task_id || '-' || COALESCE(dependency_type, 'depends'),
                   'task', task_id, 'task', depends_on_task_id, COALESCE(dependency_type, 'depends')
            FROM task_dependencies WHERE dependency_type IS NULL OR dependency_type IN ('informs', 'requires')""",
    ],
    "requirement_dependencies": [
        f"""{_INSERT_LINK})
            SELECT 'rel-' || requirement_id || '-' || depends_on_requirement_id || '-' || kind,
                   'requirement', requirement_id, 'requirement', depends_on_requirement_id, kind
            FROM (
                SELECT requirement_id, depends_on_requirement_id,
                       CASE WHEN dependency_type IN ('parent', 'refines', 'conflicts', 'relates')
                            THEN dependency_type ELSE 'depends' END AS kind
                FROM requirement_dependencies
            )""",
    ],
}

_REVERSED_REQUIREMENT_LINKS = """
    (source_type = 'task' AND target_type = 'requirement' AND relationship_type = 'implements')
    OR (source_type = 'architecture' AND target_type = 'requirement' AND relationship_type = 'addresses')
"""

LINK_VIEW_SQL = [
    """CREATE VIEW requirement_progress AS
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
        END AS completion_percentage,
        (
            SELECT COUNT(*) FROM relationships rel
            WHERE rel.source_type = 'requirement' AND rel.source_id = r.id
              AND rel.target_type = 'architecture' AND rel.relationship_type = 'addresses'
        ) AS architecture_artifacts
    FROM requirements r
    WHERE r.status != 'Deprecated'""",
    """CREATE VIEW task_hierarchy AS
    WITH RECURSIVE task_tree AS (
        SELECT t.id, t.title, t.status, NULL AS parent_task_id, 0 AS level, t.id AS root_task_id
        FROM tasks t
        WHERE NOT EXISTS (
            SELECT 1 FROM relationships rel
            WHERE rel.source_type = 'task' AND rel.source_id = t.id
              AND rel.target_type = 'task' AND rel.relationship_type = 'parent'
        )
        UNION ALL
        SELECT t.id, t.title, t.status, rel.target_id, tt.level + 1, tt.root_task_id
        FROM relationships rel
        JOIN tasks t ON t.id = rel.source_id
        JOIN task_tree tt ON tt.id = rel.target_id
        WHERE rel.source_type = 'task' AND rel.target_type = 'task' AND rel.relationship_type = 'parent'
    )
    SELECT * FROM task_tree""",
    """CREATE VIEW blocked_items AS
    WITH task_edges AS (
        SELECT source_id AS dependent_id, target_id AS dependency_id FROM relationships
        WHERE source_type = 'task' AND target_type = 'task' AND relationship_type IN ('depends', 'requires')
        UNION
        SELECT target_id, source_id FROM relationships
        WHERE source_type = 'task' AND target_type = 'task' AND relationship_type = 'blocks'
    ),
    requirement_edges AS (
        SELECT source_id AS dependent_id, target_id AS dependency_id FROM relationships
        WHERE source_type = 'requirement' AND target_type = 'requirement' AND relationship_type = 'depends'
    )
    SELECT 'task' AS item_type, t.id, t.title, t.status, GROUP_CONCAT(dt.id) AS blocking_items
    FROM tasks t
    JOIN task_edges e ON e.dependent_id = t.id
    JOIN tasks dt ON dt.id = e.dependency_id
    WHERE t.status = 'Blocked' OR (t.status = 'Not Started' AND dt.status != 'Complete')
    GROUP BY t.id
    UNION ALL
    SELECT 'requirement' AS item_type, r.id, r.title, r.status, GROUP_CONCAT(dr.id) AS blocking_items
    FROM requirements r
    JOIN requirement_edges e ON e.dependent_id = r.id
    JOIN requirements dr ON dr.id = e.dependency_id
    WHERE dr.status NOT IN ('Validated', 'Deprecated')
    GROUP BY r.id""",
    """CREATE VIEW requirement_hierarchy AS
    WITH RECURSIVE requirement_tree AS (
        SELECT
            r.id, r.title, r.status, r.priority, r.decomposition_level, r.complexity_score, r.scope_assessment,
            NULL AS parent_requirement_id,
            0 AS hierarchy_level,
            r.id AS root_requirement_id,
            r.type || '-' || CAST(r.requirement_number AS TEXT) AS path
        FROM requirements r
        WHERE NOT EXISTS (
            SELECT 1 FROM relationships rel
            WHERE rel.source_type = 'requirement' AND rel.source_id = r.id
              AND rel.target_type = 'requirement' AND rel.relationship_type = 'parent'
        )
        UNION ALL
        SELECT
            r.id, r.title, r.status, r.priority, r.decomposition_level, r.complexity_score, r.scope_assessment,
            rel.target_id,
            rt.hierarchy_level + 1,
            rt.root_requirement_id,
            rt.path || ' > ' || r.type || '-' || CAST(r.requirement_number AS TEXT)
        FROM relationships rel
        JOIN requirements r ON r.id = rel.source_id
        JOIN requirement_tree rt ON rt.id = rel.target_id
        WHERE rel.source_type = 'requirement' AND rel.target_type = 'requirement'
          AND rel.relationship_type = 'parent' AND rt.hierarchy_level < 3
    )
    SELECT * FROM requirement_tree""",
]

_TASK_COUNT = """(
    SELECT COUNT(*) FROM relationships
    WHERE source_type = 'requirement' AND source_id = {req}
      AND target_type = 'task' AND relationship_type = 'implements'
)"""
_TASKS_COMPLETED = """(
    SELECT COUNT(*) FROM relationships rel JOIN tasks t ON t.id = rel.target_id
    WHERE rel.source_type = 'requirement' AND rel.source_id = {req} AND rel.target_type = 'task'
      AND rel.relationship_type = 'implements' AND t.status = 'Complete'
)"""
_REQUIREMENT_TASK_LINK = (
    "{row}.source_type = 'requirement' AND {row}.target_type = 'task' AND {row}.relationship_type = 'implements'"
)
_REQUIREMENT_PARENT_LINK = (
    "NEW.source_type = 'requirement' AND NEW.target_type = 'requirement' AND NEW.relationship_type = 'parent'"
)

LINK_TRIGGER_SQL = [
    f"""CREATE TRIGGER update_requirement_task_count_insert
    AFTER INSERT ON relationships
    WHEN {_REQUIREMENT_TASK_LINK.format(row="NEW")}
    BEGIN
        UPDATE requirements
        SET task_count = {_TASK_COUNT.format(req="NEW.source_id")},
            tasks_completed = {_TASKS_COMPLETED.format(req="NEW.source_id")}
        WHERE id = NEW.source_id;
    END""",
    f"""CREATE TRIGGER update_requirement_task_count_delete
    AFTER DELETE ON relationships
    WHEN {_REQUIREMENT_TASK_LINK.format(row="OLD")}
    BEGIN
        UPDATE requirements
        SET task_count = {_TASK_COUNT.format(req="OLD.source_id")},
            tasks_completed = {_TASKS_COMPLETED.format(req="OLD.source_id")}
        WHERE id = OLD.source_id;
    END""",
    f"""CREATE TRIGGER update_requirement_task_completion
    AFTER UPDATE OF status ON tasks
    WHEN NEW.status = 'Complete' OR OLD.status = 'Complete'
    BEGIN
        UPDATE requirements
        SET tasks_completed = {_TASKS_COMPLETED.format(req="requirements.id")}
        WHERE id IN (
            SELECT source_id FROM relationships
            WHERE source_type = 'requirement' AND target_type = 'task'
              AND target_id = NEW.id AND relationship_type = 'implements'
        );
    END""",
    f"""CREATE TRIGGER validate_decomposition_level
    BEFORE INSERT ON relationships
    WHEN {_REQUIREMENT_PARENT_LINK}
    BEGIN
        SELECT CASE
            WHEN (SELECT decomposition_level FROM requirements WHERE id = NEW.target_id) >= 3
            THEN RAISE(ABORT, 'Maximum decomposition depth of 3 levels exceeded')
        END;
    END""",
    f"""CREATE TRIGGER set_decomposition_level
    AFTER INSERT ON relationships
    WHEN {_REQUIREMENT_PARENT_LINK}
    BEGIN
        UPDATE requirements
        SET decomposition_level = (
            SELECT COALESCE(parent.decomposition_level, 0) + 1 FROM requirements parent WHERE parent.id = NEW.target_id
        )
        WHERE id = NEW.source_id;
    END""",
    f"""CREATE TRIGGER prevent_circular_dependencies
    BEFORE INSERT ON relationships
    WHEN {_REQUIREMENT_PARENT_LINK}
    BEGIN
        SELECT CASE
            WHEN EXISTS (
                WITH RECURSIVE ancestors(id) AS (
                    SELECT NEW.target_id
                    UNION
                    SELECT rel.target_id FROM relationships rel JOIN ancestors a ON rel.source_id = a.id
                    WHERE rel.source_type = 'requirement' AND rel.target_type = 'requirement'
                      AND rel.relationship_type = 'parent'
                )
                SELECT 1 FROM ancestors WHERE id = NEW.source_id
            )
            THEN RAISE(ABORT, 'Circular dependency detected in parent-child relationship')
        END;
    END""",
]


# The old migration 7 rebuilt tasks without parent_task_id through `CREATE TABLE tasks_new AS SELECT ...`,
# dropped tasks and could fail before renaming the copy. That left the rows in a table without constraints
# and took the task indexes and triggers with it. This is tasks as the baseline and migrations 1-2 define
# it, minus parent_task_id, which this migration removes anyway.
RESTORED_TASKS_SQL = """CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    task_number INTEGER NOT NULL,
    subtask_number INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN (
        'Not Started', 'In Progress', 'Blocked', 'Complete', 'Abandoned'
    )),
    priority TEXT NOT NULL CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    effort TEXT CHECK (effort IN ('XS', 'S', 'M', 'L', 'XL')),
    user_story TEXT,
    context_research TEXT,
    acceptance_criteria TEXT,
    behavioral_specs TEXT,
    implementation_plan TEXT,
    test_plan TEXT,
    definition_of_done TEXT,
    assignee TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    github_issue_number TEXT,
    github_issue_url TEXT,
    github_etag TEXT,
    github_last_sync TEXT,
    UNIQUE(task_number, subtask_number, version)
)"""

RESTORED_TASK_OBJECTS_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee)",
    """CREATE TRIGGER IF NOT EXISTS update_task_timestamp
    AFTER UPDATE ON tasks
    BEGIN
        UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END""",
    """CREATE TRIGGER IF NOT EXISTS log_task_status_change
    AFTER UPDATE OF status ON tasks
    WHEN OLD.status != NEW.status
    BEGIN
        INSERT INTO lifecycle_events (entity_type, entity_id, event_type, from_value, to_value)
        VALUES ('task', NEW.id, 'status_change', OLD.status, NEW.status);
        UPDATE tasks
        SET completed_at = CASE WHEN NEW.status = 'Complete' THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE id = NEW.id;
    END""",
]


def _restore_half_rebuilt_tasks(conn: sqlite3.Connection) -> None:
    """Put tasks back when the old migration 7 left only its tasks_new copy.

    Rows that break a tasks constraint make the migration fail and roll back rather than being dropped.
    """
    tables = _tables(conn)
    if "tasks" in tables or "tasks_new" not in tables:
        return
    logger.warning("tasks is missing and tasks_new holds its rows (left by the old migration 7); restoring tasks")
    conn.execute(RESTORED_TASKS_SQL)
    columns = ", ".join(sorted(_columns(conn, "tasks") & _columns(conn, "tasks_new")))
    conn.execute(f"INSERT INTO tasks ({columns}) SELECT {columns} FROM tasks_new")
    conn.execute("DROP TABLE tasks_new")
    for statement in RESTORED_TASK_OBJECTS_SQL:
        conn.execute(statement)


def consolidate_links(conn: sqlite3.Connection) -> None:
    """Make relationships the only link store.

    Works on every database state seen in the field: intact legacy tables, databases where the old
    migration 7 dropped some legacy tables before failing, databases where it failed in the middle of
    rebuilding tasks, and databases where it completed. Links in tables that were already dropped cannot
    be recovered; tasks is restored from its copy, and views and triggers are rebuilt regardless.
    """
    _restore_half_rebuilt_tasks(conn)

    # Old views and triggers reference legacy tables and tasks.parent_task_id; they would block the
    # column drop and break once the tables go, so remove them first.
    for view in LINK_VIEWS:
        conn.execute(f"DROP VIEW IF EXISTS {view}")
    for trigger in LINK_TRIGGERS:
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    existing = _tables(conn)
    for table, statements in LEGACY_LINK_COPIES.items():
        if table in existing:
            for statement in statements:
                conn.execute(statement)
    if "parent_task_id" in _columns(conn, "tasks"):
        conn.execute(f"""{_INSERT_LINK})
            SELECT 'rel-' || id || '-' || parent_task_id || '-parent', 'task', id, 'task', parent_task_id, 'parent'
            FROM tasks WHERE parent_task_id IS NOT NULL AND parent_task_id != ''""")

    # create_relationship used to accept requirement links in either direction; store one direction.
    conn.execute(f"""{_INSERT_LINK}, created_at)
        SELECT 'rel-' || target_id || '-' || source_id || '-' || relationship_type,
               target_type, target_id, source_type, source_id, relationship_type, created_at
        FROM relationships WHERE {_REVERSED_REQUIREMENT_LINKS}""")
    conn.execute(f"DELETE FROM relationships WHERE {_REVERSED_REQUIREMENT_LINKS}")

    for table in LEGACY_LINK_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    if "parent_task_id" in _columns(conn, "tasks"):
        conn.execute("ALTER TABLE tasks DROP COLUMN parent_task_id")

    for statement in LINK_VIEW_SQL + LINK_TRIGGER_SQL:
        conn.execute(statement)

    # Denormalised counters were maintained from the legacy tables (or not at all); recompute them,
    # touching only rows that are wrong so updated_at isn't bumped needlessly.
    conn.execute(f"""
        UPDATE requirements
        SET task_count = counts.total, tasks_completed = counts.done
        FROM (
            SELECT id, {_TASK_COUNT.format(req="r.id")} AS total, {_TASKS_COMPLETED.format(req="r.id")} AS done
            FROM requirements r
        ) AS counts
        WHERE counts.id = requirements.id
          AND (requirements.task_count IS NOT counts.total OR requirements.tasks_completed IS NOT counts.done)
    """)


# --- migrations 9-10 ---------------------------------------------------------------------------


def add_edit_tracking(conn: sqlite3.Connection) -> None:
    """Revision counters for optimistic concurrency and per-field change events (roadmap R6a)."""
    for table in ("requirements", "tasks", "architecture"):
        if "revision" not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
    event_columns = _columns(conn, "lifecycle_events")
    for column in ("field", "reason"):
        if column not in event_columns:
            conn.execute(f"ALTER TABLE lifecycle_events ADD COLUMN {column} TEXT")


REQUIREMENT_HIERARCHY_SQL = """CREATE VIEW requirement_hierarchy AS
    WITH RECURSIVE requirement_tree AS (
        SELECT
            r.id, r.title, r.status, r.priority,
            NULL AS parent_requirement_id,
            0 AS hierarchy_level,
            r.id AS root_requirement_id,
            r.type || '-' || CAST(r.requirement_number AS TEXT) AS path
        FROM requirements r
        WHERE NOT EXISTS (
            SELECT 1 FROM relationships rel
            WHERE rel.source_type = 'requirement' AND rel.source_id = r.id
              AND rel.target_type = 'requirement' AND rel.relationship_type = 'parent'
        )
        UNION ALL
        SELECT
            r.id, r.title, r.status, r.priority,
            rel.target_id,
            rt.hierarchy_level + 1,
            rt.root_requirement_id,
            rt.path || ' > ' || r.type || '-' || CAST(r.requirement_number AS TEXT)
        FROM relationships rel
        JOIN requirements r ON r.id = rel.source_id
        JOIN requirement_tree rt ON rt.id = rel.target_id
        WHERE rel.source_type = 'requirement' AND rel.target_type = 'requirement'
          AND rel.relationship_type = 'parent'
          -- guards against cycles stored before prevent_circular_dependencies existed
          AND rt.hierarchy_level < 32
    )
    SELECT * FROM requirement_tree"""


def stop_using_decomposition_columns(conn: sqlite3.Connection) -> None:
    """Remove the objects that read requirement decomposition columns so a later migration can drop them.

    The decomposition depth limit only served the never-wired LLM decomposition feature (roadmap R6b).
    prevent_circular_dependencies does not use these columns and stays.
    """
    conn.execute("DROP VIEW IF EXISTS decomposition_candidates")
    conn.execute("DROP TRIGGER IF EXISTS validate_decomposition_level")
    conn.execute("DROP TRIGGER IF EXISTS set_decomposition_level")
    conn.execute("DROP VIEW IF EXISTS requirement_hierarchy")
    conn.execute(REQUIREMENT_HIERARCHY_SQL)


# --- migration 11 ------------------------------------------------------------------------------

# Columns no tool can set and nothing reads: the never-wired LLM decomposition feature, technical design
# document fields, and a few unused requirement fields (roadmap R6b).
DEAD_COLUMNS = {
    "requirements": (
        "decomposition_metadata",
        "decomposition_source",
        "complexity_score",
        "scope_assessment",
        "decomposition_level",
        "architecture_review",
        "gap_analysis",
        "impact_of_not_acting",
        "interface_requirements",
    ),
    "tasks": ("behavioral_specs", "context_research"),
    "architecture": ("executive_summary", "system_design", "key_decisions", "performance_considerations", "pros_cons"),
}


def drop_dead_columns(conn: sqlite3.Connection) -> None:
    """Drop the dead columns. Their CHECK constraints are column constraints and go with them."""
    conn.execute("DROP INDEX IF EXISTS idx_requirements_decomposition")
    for table, columns in DEAD_COLUMNS.items():
        existing = _columns(conn, table)
        for column in columns:
            if column in existing:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


# --- runner ------------------------------------------------------------------------------------


def log_architecture_status_changes(conn: sqlite3.Connection) -> None:
    """Record architecture decision status changes as requirements and tasks already do."""
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS log_architecture_status_change
        AFTER UPDATE OF status ON architecture
        WHEN OLD.status != NEW.status
        BEGIN
            INSERT INTO lifecycle_events (entity_type, entity_id, event_type, from_value, to_value)
            VALUES ('architecture', NEW.id, 'status_change', OLD.status, NEW.status);
        END
        """
    )


def repair_literal_updated_at(conn: sqlite3.Connection) -> None:
    """Replace architecture updated_at values stored as the text 'CURRENT_TIMESTAMP' (F-42).

    The status tools bound the string instead of using the SQL keyword. Requirements and tasks never kept it: their
    timestamp triggers overwrite updated_at after every update (and would do the same to a repair), while architecture
    has no such trigger. Each affected decision gets its latest lifecycle event time, else its created_at.
    """
    conn.execute(
        """
        UPDATE architecture
        SET updated_at = COALESCE(
            (SELECT MAX(e.occurred_at) FROM lifecycle_events e
             WHERE e.entity_type = 'architecture' AND e.entity_id = architecture.id),
            created_at,
            CURRENT_TIMESTAMP
        )
        WHERE updated_at = 'CURRENT_TIMESTAMP'
        """
    )


# --- migration 14 ------------------------------------------------------------------------------

RELATIONSHIP_COLUMNS = "id, source_type, source_id, target_type, target_id, relationship_type, created_at"

RELATIONSHIPS_WITH_SUPERSEDES_SQL = """CREATE TABLE relationships_new (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('requirement', 'task', 'architecture')),
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('requirement', 'task', 'architecture')),
    target_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL CHECK (relationship_type IN (
        'implements', 'addresses', 'depends', 'blocks', 'informs',
        'requires', 'parent', 'refines', 'conflicts', 'relates', 'supersedes'
    )),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, source_id, target_type, target_id, relationship_type)
)"""

# architecture.superseded_by mirrors the incoming supersedes link (newer -> older); relationships stays the only
# place the link is written (ADR-0001).
SUPERSEDED_BY_TRIGGER_SQL = [
    """CREATE TRIGGER set_superseded_by
    AFTER INSERT ON relationships
    WHEN NEW.relationship_type = 'supersedes'
    BEGIN
        UPDATE architecture SET superseded_by = NEW.source_id WHERE id = NEW.target_id;
    END""",
    """CREATE TRIGGER clear_superseded_by
    AFTER DELETE ON relationships
    WHEN OLD.relationship_type = 'supersedes'
    BEGIN
        UPDATE architecture SET superseded_by = NULL WHERE id = OLD.target_id AND superseded_by = OLD.source_id;
    END""",
]


def allow_supersedes_links(conn: sqlite3.Connection) -> None:
    """Add the supersedes link type and keep architecture.superseded_by in step with it (roadmap R9, ADR-0003).

    SQLite can't change a CHECK constraint in place, so relationships is rebuilt. Views and triggers that read it are
    dropped first and recreated from their stored SQL afterwards, together with its indexes and its own triggers,
    which go with the old table. Decisions whose superseded_by is already set get the matching link.
    """
    dependents = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name != 'relationships' "
        "AND (tbl_name = 'relationships' OR (type IN ('view', 'trigger') AND sql LIKE '%relationships%')) "
        "ORDER BY CASE type WHEN 'index' THEN 0 WHEN 'view' THEN 1 ELSE 2 END, name"
    ).fetchall()
    for kind, name, _ in dependents:
        if kind in ("view", "trigger"):
            conn.execute(f'DROP {kind.upper()} IF EXISTS "{name}"')

    conn.execute(RELATIONSHIPS_WITH_SUPERSEDES_SQL)
    conn.execute(
        f"INSERT INTO relationships_new ({RELATIONSHIP_COLUMNS}) SELECT {RELATIONSHIP_COLUMNS} FROM relationships"
    )
    conn.execute("DROP TABLE relationships")
    conn.execute("ALTER TABLE relationships_new RENAME TO relationships")
    for _, _, sql in dependents:
        conn.execute(sql)

    conn.execute(f"""{_INSERT_LINK})
        SELECT 'rel-' || superseded_by || '-' || id || '-supersedes',
               'architecture', superseded_by, 'architecture', id, 'supersedes'
        FROM architecture WHERE superseded_by IS NOT NULL AND superseded_by != ''""")
    for statement in SUPERSEDED_BY_TRIGGER_SQL:
        conn.execute(statement)


# --- migration 15 ------------------------------------------------------------------------------


def add_blocked_reason(conn: sqlite3.Connection) -> None:
    """Why a task is blocked, kept from the comment given with its move to Blocked (roadmap R7)."""
    if "blocked_reason" not in _columns(conn, "tasks"):
        conn.execute("ALTER TABLE tasks ADD COLUMN blocked_reason TEXT")


# --- migration 16 ------------------------------------------------------------------------------

# A task that has a parent is counted through that parent, not again on its own: create_task links every task to
# its requirements, subtasks included, so counting all implements links reported a split task twice (F-22, R14).
_IS_LEAF = """NOT EXISTS (
    SELECT 1 FROM relationships child
    WHERE child.source_type = 'task' AND child.target_type = 'task'
      AND child.target_id = rel.target_id AND child.relationship_type = 'parent'
)"""
_LEAF_TASK_COUNT = f"""(
    SELECT COUNT(*) FROM relationships rel
    WHERE rel.source_type = 'requirement' AND rel.source_id = {{req}}
      AND rel.target_type = 'task' AND rel.relationship_type = 'implements' AND {_IS_LEAF}
)"""
_LEAF_TASKS_COMPLETED = f"""(
    SELECT COUNT(*) FROM relationships rel JOIN tasks t ON t.id = rel.target_id
    WHERE rel.source_type = 'requirement' AND rel.source_id = {{req}} AND rel.target_type = 'task'
      AND rel.relationship_type = 'implements' AND t.status = 'Complete' AND {_IS_LEAF}
)"""

LEAF_COUNT_TRIGGER_SQL = [
    f"""CREATE TRIGGER update_requirement_task_count_insert
    AFTER INSERT ON relationships
    WHEN {_REQUIREMENT_TASK_LINK.format(row="NEW")}
    BEGIN
        UPDATE requirements
        SET task_count = {_LEAF_TASK_COUNT.format(req="NEW.source_id")},
            tasks_completed = {_LEAF_TASKS_COMPLETED.format(req="NEW.source_id")}
        WHERE id = NEW.source_id;
    END""",
    f"""CREATE TRIGGER update_requirement_task_count_delete
    AFTER DELETE ON relationships
    WHEN {_REQUIREMENT_TASK_LINK.format(row="OLD")}
    BEGIN
        UPDATE requirements
        SET task_count = {_LEAF_TASK_COUNT.format(req="OLD.source_id")},
            tasks_completed = {_LEAF_TASKS_COMPLETED.format(req="OLD.source_id")}
        WHERE id = OLD.source_id;
    END""",
    f"""CREATE TRIGGER update_requirement_task_completion
    AFTER UPDATE OF status ON tasks
    WHEN NEW.status = 'Complete' OR OLD.status = 'Complete'
    BEGIN
        UPDATE requirements
        SET tasks_completed = {_LEAF_TASKS_COMPLETED.format(req="requirements.id")}
        WHERE id IN (
            SELECT source_id FROM relationships
            WHERE source_type = 'requirement' AND target_type = 'task'
              AND target_id = NEW.id AND relationship_type = 'implements'
        );
    END""",
]

# A parent link changes which tasks are leaves, so the counters follow it too (roadmap R14).
LEAF_PARENT_TRIGGER_SQL = [
    f"""CREATE TRIGGER update_requirement_task_count_parent_insert
    AFTER INSERT ON relationships
    WHEN NEW.source_type = 'task' AND NEW.target_type = 'task' AND NEW.relationship_type = 'parent'
    BEGIN
        UPDATE requirements
        SET task_count = {_LEAF_TASK_COUNT.format(req="requirements.id")},
            tasks_completed = {_LEAF_TASKS_COMPLETED.format(req="requirements.id")}
        WHERE id IN (
            SELECT source_id FROM relationships
            WHERE source_type = 'requirement' AND target_type = 'task' AND relationship_type = 'implements'
              AND target_id IN (NEW.source_id, NEW.target_id)
        );
    END""",
    f"""CREATE TRIGGER update_requirement_task_count_parent_delete
    AFTER DELETE ON relationships
    WHEN OLD.source_type = 'task' AND OLD.target_type = 'task' AND OLD.relationship_type = 'parent'
    BEGIN
        UPDATE requirements
        SET task_count = {_LEAF_TASK_COUNT.format(req="requirements.id")},
            tasks_completed = {_LEAF_TASKS_COMPLETED.format(req="requirements.id")}
        WHERE id IN (
            SELECT source_id FROM relationships
            WHERE source_type = 'requirement' AND target_type = 'task' AND relationship_type = 'implements'
              AND target_id IN (OLD.source_id, OLD.target_id)
        );
    END""",
]


def count_leaf_tasks_only(conn: sqlite3.Connection) -> None:
    """Count a requirement's leaf tasks, not a parent and its subtasks both (roadmap R14, F-22).

    Rebuilds the counter triggers and recomputes the stored counters. Only task_count and tasks_completed change:
    no status is touched, and rows already correct are left alone so updated_at stays put.
    """
    for trigger in (
        "update_requirement_task_count_insert",
        "update_requirement_task_count_delete",
        "update_requirement_task_completion",
    ):
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    for statement in LEAF_COUNT_TRIGGER_SQL + LEAF_PARENT_TRIGGER_SQL:
        conn.execute(statement)

    conn.execute(f"""
        UPDATE requirements
        SET task_count = counts.total, tasks_completed = counts.done
        FROM (
            SELECT id,
                   {_LEAF_TASK_COUNT.format(req="r.id")} AS total,
                   {_LEAF_TASKS_COMPLETED.format(req="r.id")} AS done
            FROM requirements r
        ) AS counts
        WHERE counts.id = requirements.id
          AND (requirements.task_count IS NOT counts.total OR requirements.tasks_completed IS NOT counts.done)
    """)


# --- migration 17 ------------------------------------------------------------------------------


def add_task_evidence(conn: sqlite3.Connection) -> None:
    """The commit and the evidence behind a task's status, kept from its status move (roadmap R12)."""
    columns = _columns(conn, "tasks")
    for column in ("commit_ref", "evidence"):
        if column not in columns:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} TEXT")


MIGRATIONS: list[tuple[int, str, Migration]] = [
    (1, "GitHub integration fields", add_github_integration_columns),
    (2, "GitHub sync metadata fields", add_github_sync_metadata_columns),
    (3, "Requirement decomposition extension", add_decomposition_columns),
    (4, "Fix blocked_items view column reference (superseded by 8)", superseded),
    (5, "Create unified relationships table", create_relationships_table),
    (6, "Consolidate relationship data (superseded by 8)", superseded),
    (7, "Remove redundant relationship tables (superseded by 8)", superseded),
    (8, "Consolidate all links into relationships", consolidate_links),
    (9, "Edit tracking: revision counters and per-field change events", add_edit_tracking),
    (10, "Stop using requirement decomposition columns", stop_using_decomposition_columns),
    (11, "Drop dead columns", drop_dead_columns),
    (12, "Log architecture status changes", log_architecture_status_changes),
    (13, "Repair architecture updated_at stored as the text CURRENT_TIMESTAMP", repair_literal_updated_at),
    (14, "Allow supersedes links and keep superseded_by in step", allow_supersedes_links),
    (15, "Keep the reason a task is blocked", add_blocked_reason),
    (16, "Count leaf tasks only in requirement progress", count_leaf_tasks_only),
    (17, "Keep the commit and evidence behind a task's status", add_task_evidence),
]


def apply_all_migrations(db_path: str, target_version: int | None = None) -> int:
    """Apply pending migrations up to target_version (default: latest) and return the resulting version.

    Raises MigrationError when a migration fails; that migration is rolled back completely.
    """
    target = MIGRATIONS[-1][0] if target_version is None else target_version
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=30)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )
        """)
        for version, description, migrate in MIGRATIONS:
            if version > target:
                break
            # IMMEDIATE takes the write lock before re-reading the version, so two servers starting
            # against the same database cannot both apply a migration.
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
                if current >= version:
                    conn.execute("COMMIT")
                    continue
                logger.info(f"Applying migration {version}: {description}")
                migrate(conn)
                conn.execute("INSERT INTO schema_version (version, description) VALUES (?, ?)", (version, description))
                conn.execute("COMMIT")
            except Exception as e:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise MigrationError(f"Migration {version} ({description}) failed and was rolled back: {e}") from e
        return conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
    finally:
        conn.close()
