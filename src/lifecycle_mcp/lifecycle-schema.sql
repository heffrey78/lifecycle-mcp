-- Software Lifecycle Management Database Schema
-- Designed for MCP server integration with Claude Code and human interfaces

-- Requirements table - the source of truth for what needs to be built
CREATE TABLE requirements (
    id TEXT PRIMARY KEY, -- REQ-XXXX-TYPE-VV format
    requirement_number INTEGER NOT NULL, -- XXXX part for queries
    type TEXT NOT NULL CHECK (type IN ('FUNC', 'NFUNC', 'TECH', 'BUS', 'INTF')),
    version INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN (
        'Draft', 'Under Review', 'Approved', 'Architecture', 
        'Ready', 'Implemented', 'Validated', 'Deprecated'
    )),
    priority TEXT NOT NULL CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    risk_level TEXT CHECK (risk_level IN ('High', 'Medium', 'Low')),
    business_value TEXT,
    architecture_review TEXT CHECK (architecture_review IN ('Not Required', 'Required', 'Complete')),
    
    -- Content fields
    current_state TEXT,
    desired_state TEXT,
    gap_analysis TEXT,
    impact_of_not_acting TEXT,
    functional_requirements TEXT, -- JSON array
    nonfunctional_requirements TEXT, -- JSON object
    technical_constraints TEXT, -- JSON object
    business_rules TEXT, -- JSON array
    interface_requirements TEXT, -- JSON object
    acceptance_criteria TEXT, -- JSON array
    validation_metrics TEXT, -- JSON array
    out_of_scope TEXT, -- JSON array
    
    -- Metadata
    author TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Denormalized for performance
    task_count INTEGER DEFAULT 0,
    tasks_completed INTEGER DEFAULT 0,
    
    UNIQUE(requirement_number, type, version)
);

-- Tasks table - implementation work items
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, -- TASK-XXXX-YY-ZZ format
    task_number INTEGER NOT NULL, -- XXXX part
    subtask_number INTEGER NOT NULL DEFAULT 0, -- YY part
    version INTEGER NOT NULL DEFAULT 0, -- ZZ part
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN (
        'Not Started', 'In Progress', 'Blocked', 'Complete', 'Abandoned'
    )),
    priority TEXT NOT NULL CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    effort TEXT CHECK (effort IN ('XS', 'S', 'M', 'L', 'XL')),
    
    -- Content
    user_story TEXT,
    context_research TEXT, -- JSON object
    acceptance_criteria TEXT, -- JSON array
    behavioral_specs TEXT, -- Gherkin scenarios
    implementation_plan TEXT, -- JSON object
    test_plan TEXT, -- JSON object
    definition_of_done TEXT, -- JSON array
    
    -- Metadata
    assignee TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- GitHub Integration
    github_issue_number TEXT,
    github_issue_url TEXT,
    
    -- Relationships
    parent_task_id TEXT REFERENCES tasks(id),
    
    UNIQUE(task_number, subtask_number, version)
);

-- Architecture artifacts
CREATE TABLE architecture (
    id TEXT PRIMARY KEY, -- ADR-XXXX or TDD-XXXX-Component-VV
    type TEXT NOT NULL CHECK (type IN ('ADR', 'TDD', 'INTG')),
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'Proposed', 'Accepted', 'Rejected', 'Deprecated', 'Superseded', 
        'Draft', 'Under Review', 'Approved', 'Implemented'
    )),
    
    -- Content
    context TEXT,
    decision_drivers TEXT, -- JSON array
    considered_options TEXT, -- JSON array
    decision_outcome TEXT,
    consequences TEXT, -- JSON object {good: [], bad: [], neutral: []}
    pros_cons TEXT, -- JSON object per option
    implementation_notes TEXT,
    validation_criteria TEXT, -- JSON array
    
    -- TDD specific fields
    executive_summary TEXT,
    system_design TEXT, -- JSON object with diagrams
    key_decisions TEXT, -- JSON object
    performance_considerations TEXT, -- JSON object
    risk_assessment TEXT, -- JSON array of {risk, likelihood, impact, mitigation}
    
    -- Metadata
    authors TEXT, -- JSON array
    deciders TEXT, -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    superseded_by TEXT REFERENCES architecture(id)
);

-- Link tables for many-to-many relationships
CREATE TABLE requirement_tasks (
    requirement_id TEXT NOT NULL REFERENCES requirements(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (requirement_id, task_id)
);

CREATE TABLE requirement_architecture (
    requirement_id TEXT NOT NULL REFERENCES requirements(id),
    architecture_id TEXT NOT NULL REFERENCES architecture(id),
    relationship_type TEXT, -- 'addresses', 'modifies', 'implements'
    PRIMARY KEY (requirement_id, architecture_id)
);

CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    depends_on_task_id TEXT NOT NULL REFERENCES tasks(id),
    dependency_type TEXT CHECK (dependency_type IN ('blocks', 'informs', 'requires')),
    PRIMARY KEY (task_id, depends_on_task_id)
);

CREATE TABLE requirement_dependencies (
    requirement_id TEXT NOT NULL REFERENCES requirements(id),
    depends_on_requirement_id TEXT NOT NULL REFERENCES requirements(id),
    dependency_type TEXT, -- 'parent', 'refines', 'conflicts', 'relates'
    PRIMARY KEY (requirement_id, depends_on_requirement_id)
);

-- Approvals tracking
CREATE TABLE approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('requirement', 'architecture')),
    entity_id TEXT NOT NULL,
    role TEXT NOT NULL, -- 'Product Owner', 'Technical Lead', 'Architecture', 'Security'
    approver_name TEXT NOT NULL,
    approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    comments TEXT,
    UNIQUE(entity_type, entity_id, role)
);

-- Review comments and discussions
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('requirement', 'task', 'architecture')),
    entity_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved BOOLEAN DEFAULT FALSE
);

-- Metrics and monitoring
CREATE TABLE lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL, -- 'status_change', 'created', 'updated', 'approved'
    from_value TEXT,
    to_value TEXT,
    actor TEXT,
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Views for common queries
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
    COUNT(DISTINCT a.id) as architecture_artifacts
FROM requirements r
LEFT JOIN requirement_architecture ra ON r.id = ra.requirement_id
LEFT JOIN architecture a ON ra.architecture_id = a.id
WHERE r.status != 'Deprecated'
GROUP BY r.id;

CREATE VIEW task_hierarchy AS
WITH RECURSIVE task_tree AS (
    -- Base case: top-level tasks
    SELECT 
        t.id,
        t.title,
        t.status,
        t.parent_task_id,
        0 as level,
        t.id as root_task_id
    FROM tasks t
    WHERE t.parent_task_id IS NULL
    
    UNION ALL
    
    -- Recursive case: subtasks
    SELECT 
        t.id,
        t.title,
        t.status,
        t.parent_task_id,
        tt.level + 1,
        tt.root_task_id
    FROM tasks t
    JOIN task_tree tt ON t.parent_task_id = tt.id
)
SELECT * FROM task_tree;

CREATE VIEW blocked_items AS
SELECT 
    'task' as item_type,
    t.id,
    t.title,
    t.status,
    GROUP_CONCAT(dt.depends_on_task_id) as blocking_items
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
GROUP BY r.id;

-- Indexes for performance
CREATE INDEX idx_requirements_status ON requirements(status);
CREATE INDEX idx_requirements_priority ON requirements(priority);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_assignee ON tasks(assignee);
CREATE INDEX idx_lifecycle_events_entity ON lifecycle_events(entity_type, entity_id);
CREATE INDEX idx_approvals_entity ON approvals(entity_type, entity_id);

-- Triggers for automatic updates
CREATE TRIGGER update_requirement_timestamp 
AFTER UPDATE ON requirements
BEGIN
    UPDATE requirements SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER update_task_timestamp 
AFTER UPDATE ON tasks
BEGIN
    UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER log_requirement_status_change
AFTER UPDATE OF status ON requirements
WHEN OLD.status != NEW.status
BEGIN
    INSERT INTO lifecycle_events (entity_type, entity_id, event_type, from_value, to_value)
    VALUES ('requirement', NEW.id, 'status_change', OLD.status, NEW.status);
END;

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
END;

-- Update requirement task counts
CREATE TRIGGER update_requirement_task_count_insert
AFTER INSERT ON requirement_tasks
BEGIN
    UPDATE requirements 
    SET task_count = (
        SELECT COUNT(*) FROM requirement_tasks WHERE requirement_id = NEW.requirement_id
    )
    WHERE id = NEW.requirement_id;
END;

CREATE TRIGGER update_requirement_task_completion
AFTER UPDATE OF status ON tasks
WHEN NEW.status = 'Complete' OR OLD.status = 'Complete'
BEGIN
    UPDATE requirements 
    SET tasks_completed = (
        SELECT COUNT(*) 
        FROM requirement_tasks rt
        JOIN tasks t ON rt.task_id = t.id
        WHERE rt.requirement_id = requirements.id AND t.status = 'Complete'
    )
    WHERE id IN (
        SELECT requirement_id FROM requirement_tasks WHERE task_id = NEW.id
    );
END;