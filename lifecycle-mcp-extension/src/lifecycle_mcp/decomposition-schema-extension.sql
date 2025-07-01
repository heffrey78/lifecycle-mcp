-- Database schema extensions for requirement decomposition
-- Add to existing lifecycle-schema.sql

-- Add decomposition-specific metadata to requirements table
ALTER TABLE requirements ADD COLUMN decomposition_metadata TEXT; -- JSON for LLM analysis results
ALTER TABLE requirements ADD COLUMN decomposition_source TEXT CHECK (decomposition_source IN ('manual', 'llm_automatic', 'llm_suggested'));
ALTER TABLE requirements ADD COLUMN complexity_score INTEGER CHECK (complexity_score BETWEEN 1 AND 10);
ALTER TABLE requirements ADD COLUMN scope_assessment TEXT CHECK (scope_assessment IN ('single_feature', 'multiple_features', 'complex_workflow', 'epic'));
ALTER TABLE requirements ADD COLUMN decomposition_level INTEGER DEFAULT 0 CHECK (decomposition_level BETWEEN 0 AND 3); -- Max 3 levels

-- Create view for requirement hierarchy (similar to task_hierarchy)
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
        rt.path || ' > ' || r.type || '-' || CAST(r.requirement_number AS TEXT)
    FROM requirements r
    JOIN requirement_dependencies rd ON r.id = rd.requirement_id
    JOIN requirement_tree rt ON rd.depends_on_requirement_id = rt.id
    WHERE rd.dependency_type = 'parent' AND rt.hierarchy_level < 3 -- Max 3 levels
)
SELECT * FROM requirement_tree;

-- View for decomposition candidates (requirements that might need decomposition)
CREATE VIEW decomposition_candidates AS
SELECT 
    r.id,
    r.title,
    r.status,
    r.complexity_score,
    r.scope_assessment,
    r.decomposition_level,
    (LENGTH(r.functional_requirements) - LENGTH(REPLACE(r.functional_requirements, ',', '')) + 1) as functional_req_count,
    (LENGTH(r.acceptance_criteria) - LENGTH(REPLACE(r.acceptance_criteria, ',', '')) + 1) as acceptance_criteria_count,
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
        OR r.scope_assessment IN ('multiple_features', 'complex_workflow', 'epic')
        OR (LENGTH(r.functional_requirements) - LENGTH(REPLACE(r.functional_requirements, ',', '')) + 1) > 5
    );

-- Add index for parent-child queries
CREATE INDEX idx_requirement_dependencies_parent ON requirement_dependencies(depends_on_requirement_id, dependency_type);
CREATE INDEX idx_requirements_decomposition ON requirements(decomposition_level, complexity_score, scope_assessment);

-- Trigger to validate decomposition hierarchy depth
CREATE TRIGGER validate_decomposition_level
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
END;

-- Trigger to automatically set decomposition_level when creating parent-child relationships
CREATE TRIGGER set_decomposition_level
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
END;

-- Trigger to prevent circular dependencies in parent-child relationships
CREATE TRIGGER prevent_circular_dependencies
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
            SELECT 1 FROM circular_check WHERE ancestor_id = NEW.requirement_id
        )
        THEN RAISE(ABORT, 'Circular dependency detected in parent-child relationship')
    END;
END;