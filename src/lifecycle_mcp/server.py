#!/usr/bin/env python3
"""
MCP Server for Software Lifecycle Management
Provides structured access to requirements, tasks, and architecture artifacts
"""

import json
import sqlite3
import os
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

logger = logging.getLogger(__name__)

# Initialize the database path
DB_PATH = os.environ.get("LIFECYCLE_DB", "lifecycle.db")

def init_database():
    """Initialize database with schema if needed"""
    if not Path(DB_PATH).exists():
        conn = sqlite3.connect(DB_PATH)
        schema_path = Path(__file__).parent / "lifecycle-schema.sql"
        if schema_path.exists():
            with open(schema_path, "r") as f:
                conn.executescript(f.read())
        conn.close()

# Initialize database on startup
init_database()

# Create the server instance
server = Server("lifecycle-management")

@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools"""
    return [
        Tool(
            name="create_requirement",
            description="Create a new requirement from interview data",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["FUNC", "NFUNC", "TECH", "BUS", "INTF"]},
                    "title": {"type": "string"},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                    "current_state": {"type": "string"},
                    "desired_state": {"type": "string"},
                    "functional_requirements": {"type": "array", "items": {"type": "string"}},
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    "business_value": {"type": "string"},
                    "risk_level": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "author": {"type": "string"}
                },
                "required": ["type", "title", "priority", "current_state", "desired_state"]
            }
        ),
        Tool(
            name="update_requirement_status",
            description="Move requirement through lifecycle states",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string"},
                    "new_status": {"type": "string", "enum": [
                        "Draft", "Under Review", "Approved", "Architecture", 
                        "Ready", "Implemented", "Validated", "Deprecated"
                    ]},
                    "comment": {"type": "string"}
                },
                "required": ["requirement_id", "new_status"]
            }
        ),
        Tool(
            name="query_requirements",
            description="Search and filter requirements",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "priority": {"type": "string"},
                    "type": {"type": "string"},
                    "search_text": {"type": "string"}
                }
            }
        ),
        Tool(
            name="create_task",
            description="Create implementation task from requirement",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                    "effort": {"type": "string", "enum": ["XS", "S", "M", "L", "XL"]},
                    "user_story": {"type": "string"},
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                    "parent_task_id": {"type": "string"},
                    "assignee": {"type": "string"}
                },
                "required": ["requirement_ids", "title", "priority"]
            }
        ),
        Tool(
            name="update_task_status",
            description="Update task progress",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "new_status": {"type": "string", "enum": [
                        "Not Started", "In Progress", "Blocked", "Complete", "Abandoned"
                    ]},
                    "comment": {"type": "string"},
                    "assignee": {"type": "string"}
                },
                "required": ["task_id", "new_status"]
            }
        ),
        Tool(
            name="create_architecture_decision",
            description="Record architecture decision (ADR)",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "context": {"type": "string"},
                    "decision": {"type": "string"},
                    "consequences": {"type": "object"},
                    "decision_drivers": {"type": "array", "items": {"type": "string"}},
                    "considered_options": {"type": "array", "items": {"type": "string"}},
                    "authors": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["requirement_ids", "title", "context", "decision"]
            }
        ),
        Tool(
            name="get_requirement_details",
            description="Get full requirement with all relationships",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string"}
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="get_project_status",
            description="Get overall project health metrics",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_blocked": {"type": "boolean"}
                }
            }
        ),
        Tool(
            name="trace_requirement",
            description="Trace requirement through implementation",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string"}
                },
                "required": ["requirement_id"]
            }
        ),
        Tool(
            name="get_task_details",
            description="Get full task details with dependencies",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"}
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="query_tasks",
            description="Search and filter tasks",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "priority": {"type": "string"},
                    "assignee": {"type": "string"},
                    "requirement_id": {"type": "string"}
                }
            }
        ),
        Tool(
            name="update_architecture_status",
            description="Update architecture decision status",
            inputSchema={
                "type": "object",
                "properties": {
                    "architecture_id": {"type": "string"},
                    "new_status": {"type": "string", "enum": [
                        "Proposed", "Accepted", "Rejected", "Deprecated", "Superseded",
                        "Draft", "Under Review", "Approved", "Implemented"
                    ]},
                    "comment": {"type": "string"}
                },
                "required": ["architecture_id", "new_status"]
            }
        ),
        Tool(
            name="query_architecture_decisions",
            description="Search and filter architecture decisions",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "type": {"type": "string"},
                    "requirement_id": {"type": "string"},
                    "search_text": {"type": "string"}
                }
            }
        ),
        Tool(
            name="get_architecture_details",
            description="Get full architecture decision details",
            inputSchema={
                "type": "object",
                "properties": {
                    "architecture_id": {"type": "string"}
                },
                "required": ["architecture_id"]
            }
        ),
        Tool(
            name="add_architecture_review",
            description="Add review comment to architecture decision",
            inputSchema={
                "type": "object",
                "properties": {
                    "architecture_id": {"type": "string"},
                    "comment": {"type": "string"},
                    "reviewer": {"type": "string"}
                },
                "required": ["architecture_id", "comment"]
            }
        ),
        Tool(
            name="start_requirement_interview",
            description="Start interactive requirement gathering interview",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_context": {"type": "string"},
                    "stakeholder_role": {"type": "string"}
                }
            }
        ),
        Tool(
            name="continue_requirement_interview",
            description="Continue requirement interview with answers",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "answers": {"type": "object"}
                },
                "required": ["session_id", "answers"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls"""
    
    if name == "create_requirement":
        return await handle_create_requirement(**arguments)
    elif name == "update_requirement_status":
        return await handle_update_requirement_status(**arguments)
    elif name == "query_requirements":
        return await handle_query_requirements(**arguments)
    elif name == "create_task":
        return await handle_create_task(**arguments)
    elif name == "update_task_status":
        return await handle_update_task_status(**arguments)
    elif name == "create_architecture_decision":
        return await handle_create_architecture_decision(**arguments)
    elif name == "get_requirement_details":
        return await handle_get_requirement_details(**arguments)
    elif name == "get_project_status":
        return await handle_get_project_status(**arguments)
    elif name == "trace_requirement":
        return await handle_trace_requirement(**arguments)
    elif name == "get_task_details":
        return await handle_get_task_details(**arguments)
    elif name == "query_tasks":
        return await handle_query_tasks(**arguments)
    elif name == "update_architecture_status":
        return await handle_update_architecture_status(**arguments)
    elif name == "query_architecture_decisions":
        return await handle_query_architecture_decisions(**arguments)
    elif name == "get_architecture_details":
        return await handle_get_architecture_details(**arguments)
    elif name == "add_architecture_review":
        return await handle_add_architecture_review(**arguments)
    elif name == "start_requirement_interview":
        return await handle_start_requirement_interview(**arguments)
    elif name == "continue_requirement_interview":
        return await handle_continue_requirement_interview(**arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def handle_create_requirement(**params) -> List[TextContent]:
    """Create a new requirement"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Get next requirement number
        cur.execute("""
            SELECT COALESCE(MAX(requirement_number), 0) + 1 
            FROM requirements 
            WHERE type = ?
        """, (params["type"],))
        req_number = cur.fetchone()[0]
        
        req_id = f"REQ-{req_number:04d}-{params['type']}-00"
        
        # Insert requirement
        cur.execute("""
            INSERT INTO requirements (
                id, requirement_number, type, version, title, priority,
                current_state, desired_state, functional_requirements,
                acceptance_criteria, author, business_value, risk_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req_id, req_number, params["type"], 0, params["title"], 
            params["priority"], params["current_state"], params["desired_state"],
            json.dumps(params.get("functional_requirements", [])),
            json.dumps(params.get("acceptance_criteria", [])),
            params.get("author", "MCP User"),
            params.get("business_value", ""),
            params.get("risk_level", "Medium")
        ))
        
        # Log event
        cur.execute("""
            INSERT INTO lifecycle_events (entity_type, entity_id, event_type, actor)
            VALUES ('requirement', ?, 'created', ?)
        """, (req_id, params.get("author", "MCP User")))
        
        conn.commit()
        
        return [TextContent(
            type="text",
            text=f"Created requirement {req_id}: {params['title']}"
        )]
        
    except Exception as e:
        conn.rollback()
        return [TextContent(type="text", text=f"Error creating requirement: {str(e)}")]
    finally:
        conn.close()

async def handle_update_requirement_status(**params) -> List[TextContent]:
    """Update requirement status with validation"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Validate transition
        cur.execute("SELECT status FROM requirements WHERE id = ?", (params["requirement_id"],))
        current = cur.fetchone()
        if not current:
            return [TextContent(type="text", text="Requirement not found")]
        
        current_status = current[0]
        new_status = params["new_status"]
        
        # Validate state transition
        valid_transitions = {
            "Draft": ["Under Review", "Deprecated"],
            "Under Review": ["Draft", "Approved", "Deprecated"],
            "Approved": ["Architecture", "Ready", "Deprecated"],
            "Architecture": ["Ready", "Approved"],
            "Ready": ["Implemented", "Deprecated"],
            "Implemented": ["Validated", "Ready"],
            "Validated": ["Deprecated"],
            "Deprecated": []
        }
        
        if new_status not in valid_transitions.get(current_status, []):
            return [TextContent(
                type="text", 
                text=f"Invalid transition from {current_status} to {new_status}"
            )]
        
        # Update status
        cur.execute("""
            UPDATE requirements 
            SET status = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (new_status, params["requirement_id"]))
        
        # Add review comment if provided
        if params.get("comment"):
            cur.execute("""
                INSERT INTO reviews (entity_type, entity_id, reviewer, comment)
                VALUES ('requirement', ?, 'MCP User', ?)
            """, (params["requirement_id"], params["comment"]))
        
        conn.commit()
        
        return [TextContent(
            type="text",
            text=f"Updated {params['requirement_id']} from {current_status} to {new_status}"
        )]
        
    except Exception as e:
        conn.rollback()
        return [TextContent(type="text", text=f"Error updating status: {str(e)}")]
    finally:
        conn.close()

async def handle_query_requirements(**params) -> List[TextContent]:
    """Query requirements with filters"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    query = "SELECT * FROM requirements WHERE 1=1"
    query_params = []
    
    if params.get("status"):
        query += " AND status = ?"
        query_params.append(params["status"])
    
    if params.get("priority"):
        query += " AND priority = ?"
        query_params.append(params["priority"])
    
    if params.get("type"):
        query += " AND type = ?"
        query_params.append(params["type"])
    
    if params.get("search_text"):
        query += " AND (title LIKE ? OR desired_state LIKE ?)"
        search = f"%{params['search_text']}%"
        query_params.extend([search, search])
    
    query += " ORDER BY priority, created_at DESC"
    
    cur.execute(query, query_params)
    requirements = cur.fetchall()
    
    if not requirements:
        return [TextContent(type="text", text="No requirements found matching criteria")]
    
    result = f"Found {len(requirements)} requirements:\n\n"
    for req in requirements:
        result += f"- {req['id']}: {req['title']} [{req['status']}] {req['priority']}\n"
    
    return [TextContent(type="text", text=result)]

async def handle_create_task(**params) -> List[TextContent]:
    """Create task linked to requirements"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Get next task number
        cur.execute("SELECT COALESCE(MAX(task_number), 0) + 1 FROM tasks")
        task_number = cur.fetchone()[0]
        
        # Determine subtask number
        subtask_number = 0
        if params.get("parent_task_id"):
            cur.execute("""
                SELECT task_number, COALESCE(MAX(subtask_number), 0) + 1 
                FROM tasks 
                WHERE parent_task_id = ?
                GROUP BY task_number
            """, (params["parent_task_id"],))
            result = cur.fetchone()
            if result:
                task_number = result[0]
                subtask_number = result[1]
        
        task_id = f"TASK-{task_number:04d}-{subtask_number:02d}-00"
        
        # Insert task
        cur.execute("""
            INSERT INTO tasks (
                id, task_number, subtask_number, version, title, priority,
                effort, user_story, acceptance_criteria, parent_task_id, assignee
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, task_number, subtask_number, 0, params["title"],
            params["priority"], params.get("effort"), params.get("user_story"),
            json.dumps(params.get("acceptance_criteria", [])),
            params.get("parent_task_id"), params.get("assignee")
        ))
        
        # Link to requirements
        for req_id in params["requirement_ids"]:
            cur.execute("""
                INSERT INTO requirement_tasks (requirement_id, task_id)
                VALUES (?, ?)
            """, (req_id, task_id))
        
        conn.commit()
        
        return [TextContent(
            type="text",
            text=f"Created task {task_id}: {params['title']}"
        )]
        
    except Exception as e:
        conn.rollback()
        return [TextContent(type="text", text=f"Error creating task: {str(e)}")]
    finally:
        conn.close()

async def handle_update_task_status(**params) -> List[TextContent]:
    """Update task status"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Get current task
        cur.execute("SELECT status, assignee FROM tasks WHERE id = ?", (params["task_id"],))
        current = cur.fetchone()
        if not current:
            return [TextContent(type="text", text="Task not found")]
        
        current_status, current_assignee = current
        new_status = params["new_status"]
        
        # Update task
        update_fields = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        update_values = [new_status]
        
        if params.get("assignee"):
            update_fields.append("assignee = ?")
            update_values.append(params["assignee"])
        
        update_values.append(params["task_id"])
        
        cur.execute(f"""
            UPDATE tasks 
            SET {', '.join(update_fields)}
            WHERE id = ?
        """, update_values)
        
        # Add comment if provided
        if params.get("comment"):
            cur.execute("""
                INSERT INTO reviews (entity_type, entity_id, reviewer, comment)
                VALUES ('task', ?, 'MCP User', ?)
            """, (params["task_id"], params["comment"]))
        
        conn.commit()
        
        return [TextContent(
            type="text",
            text=f"Updated task {params['task_id']} from {current_status} to {new_status}"
        )]
        
    except Exception as e:
        conn.rollback()
        return [TextContent(type="text", text=f"Error updating task: {str(e)}")]
    finally:
        conn.close()

async def handle_create_architecture_decision(**params) -> List[TextContent]:
    """Create ADR"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Get next ADR number
        cur.execute("""
            SELECT COALESCE(MAX(CAST(SUBSTR(id, 5, 4) AS INTEGER)), 0) + 1 
            FROM architecture 
            WHERE type = 'ADR'
        """)
        adr_number = cur.fetchone()[0]
        
        adr_id = f"ADR-{adr_number:04d}"
        
        # Insert ADR
        cur.execute("""
            INSERT INTO architecture (
                id, type, title, status, context, decision_outcome,
                decision_drivers, considered_options, consequences, authors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            adr_id, "ADR", params["title"], "Proposed", params["context"],
            params["decision"], 
            json.dumps(params.get("decision_drivers", [])),
            json.dumps(params.get("considered_options", [])),
            json.dumps(params.get("consequences", {})),
            json.dumps(params.get("authors", ["MCP User"]))
        ))
        
        # Link to requirements
        for req_id in params["requirement_ids"]:
            cur.execute("""
                INSERT INTO requirement_architecture (requirement_id, architecture_id, relationship_type)
                VALUES (?, ?, 'addresses')
            """, (req_id, adr_id))
        
        conn.commit()
        
        return [TextContent(
            type="text",
            text=f"Created architecture decision {adr_id}: {params['title']}"
        )]
        
    except Exception as e:
        conn.rollback()
        return [TextContent(type="text", text=f"Error creating ADR: {str(e)}")]
    finally:
        conn.close()

async def handle_get_requirement_details(**params) -> List[TextContent]:
    """Get full requirement details"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    try:
        # Get requirement
        cur.execute("SELECT * FROM requirements WHERE id = ?", (params["requirement_id"],))
        req = cur.fetchone()
        if not req:
            return [TextContent(type="text", text="Requirement not found")]
        
        # Build detailed report
        report = f"""# Requirement Details: {req['id']}

## Basic Information
- **Title**: {req['title']}
- **Type**: {req['type']}
- **Status**: {req['status']}
- **Priority**: {req['priority']}
- **Risk Level**: {req['risk_level']}
- **Author**: {req['author']}
- **Created**: {req['created_at']}
- **Updated**: {req['updated_at']}

## Problem Definition
**Current State**: {req['current_state']}

**Desired State**: {req['desired_state']}

**Business Value**: {req['business_value'] or 'Not specified'}

## Requirements Details
"""
        
        if req['functional_requirements']:
            func_reqs = json.loads(req['functional_requirements'])
            report += "### Functional Requirements\n"
            for fr in func_reqs:
                report += f"- {fr}\n"
        
        if req['acceptance_criteria']:
            acc_criteria = json.loads(req['acceptance_criteria'])
            report += "\n### Acceptance Criteria\n"
            for ac in acc_criteria:
                report += f"- {ac}\n"
        
        # Get linked tasks
        cur.execute("""
            SELECT t.* FROM tasks t
            JOIN requirement_tasks rt ON t.id = rt.task_id
            WHERE rt.requirement_id = ?
        """, (params["requirement_id"],))
        tasks = cur.fetchall()
        
        if tasks:
            report += f"\n## Linked Tasks ({len(tasks)})\n"
            for task in tasks:
                report += f"- {task['id']}: {task['title']} [{task['status']}]\n"
        
        return [TextContent(type="text", text=report)]
        
    finally:
        conn.close()

async def handle_get_project_status(**params) -> List[TextContent]:
    """Get overall project health metrics"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    try:
        # Get requirement stats
        cur.execute("""
            SELECT 
                status, 
                COUNT(*) as count,
                AVG(CASE 
                    WHEN task_count = 0 THEN 0 
                    ELSE CAST(tasks_completed AS FLOAT) / task_count * 100 
                END) as avg_completion
            FROM requirements
            WHERE status != 'Deprecated'
            GROUP BY status
        """)
        req_stats = cur.fetchall()
        
        # Get task stats
        cur.execute("""
            SELECT status, COUNT(*) as count
            FROM tasks
            WHERE status != 'Abandoned'
            GROUP BY status
        """)
        task_stats = cur.fetchall()
        
        # Get blocked items
        blocked = []
        if params.get("include_blocked", True):
            try:
                cur.execute("SELECT * FROM blocked_items")
                blocked = cur.fetchall()
            except sqlite3.OperationalError:
                # View might not work if no dependencies exist yet
                blocked = []
        
        # Build report
        report = """# Project Status Dashboard

## Requirements Overview
"""
        total_reqs = sum(r['count'] for r in req_stats) if req_stats else 0
        if total_reqs > 0:
            for stat in req_stats:
                percentage = (stat['count'] / total_reqs * 100)
                report += f"- **{stat['status']}**: {stat['count']} ({percentage:.1f}%)"
                if stat['avg_completion']:
                    report += f" - Avg {stat['avg_completion']:.1f}% complete"
                report += "\n"
        else:
            report += "- No requirements found\n"
        
        report += "\n## Tasks Overview\n"
        total_tasks = sum(t['count'] for t in task_stats) if task_stats else 0
        if total_tasks > 0:
            for stat in task_stats:
                percentage = (stat['count'] / total_tasks * 100)
                report += f"- **{stat['status']}**: {stat['count']} ({percentage:.1f}%)\n"
        else:
            report += "- No tasks found\n"
        
        if blocked:
            report += f"\n## ⚠️ Blocked Items ({len(blocked)})\n"
            for item in blocked[:10]:  # Show first 10
                report += f"- {item['item_type'].upper()} {item['id']}: {item['title']}\n"
                report += f"  Blocked by: {item['blocking_items']}\n"
        
        return [TextContent(type="text", text=report)]
        
    finally:
        conn.close()

async def handle_trace_requirement(**params) -> List[TextContent]:
    """Trace requirement through full lifecycle"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    try:
        # Get requirement
        cur.execute("SELECT * FROM requirements WHERE id = ?", (params["requirement_id"],))
        req = cur.fetchone()
        if not req:
            return [TextContent(type="text", text="Requirement not found")]
        
        # Get tasks
        cur.execute("""
            SELECT t.* FROM tasks t
            JOIN requirement_tasks rt ON t.id = rt.task_id
            WHERE rt.requirement_id = ?
            ORDER BY t.task_number, t.subtask_number
        """, (params["requirement_id"],))
        tasks = cur.fetchall()
        
        # Get architecture
        cur.execute("""
            SELECT a.* FROM architecture a
            JOIN requirement_architecture ra ON a.id = ra.architecture_id
            WHERE ra.requirement_id = ?
        """, (params["requirement_id"],))
        architecture = cur.fetchall()
        
        # Build trace report
        report = f"""# Requirement Trace: {req['id']}

## Requirement Details
- **Title**: {req['title']}
- **Status**: {req['status']}
- **Priority**: {req['priority']}
- **Created**: {req['created_at']}
- **Progress**: {req['tasks_completed']}/{req['task_count']} tasks complete

## Current State
{req['current_state']}

## Desired State
{req['desired_state']}

## Implementation Tasks ({len(tasks)})
"""
        for task in tasks:
            report += f"- {task['id']}: {task['title']} [{task['status']}]"
            if task['assignee']:
                report += f" (Assigned: {task['assignee']})"
            report += "\n"
        
        if architecture:
            report += f"\n## Architecture Decisions ({len(architecture)})\n"
            for arch in architecture:
                report += f"- {arch['id']}: {arch['title']} [{arch['status']}]\n"
        
        return [TextContent(type="text", text=report)]
        
    finally:
        conn.close()

async def handle_get_task_details(**params) -> List[TextContent]:
    """Get full task details"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    try:
        # Get task
        cur.execute("SELECT * FROM tasks WHERE id = ?", (params["task_id"],))
        task = cur.fetchone()
        if not task:
            return [TextContent(type="text", text="Task not found")]
        
        # Build report
        report = f"""# Task Details: {task['id']}

## Basic Information
- **Title**: {task['title']}
- **Status**: {task['status']}
- **Priority**: {task['priority']}
- **Effort**: {task['effort']}
- **Assignee**: {task['assignee'] or 'Unassigned'}
- **Created**: {task['created_at']}
- **Updated**: {task['updated_at']}

## Description
{task['user_story'] or 'No user story provided'}

## Acceptance Criteria
"""
        if task['acceptance_criteria']:
            criteria = json.loads(task['acceptance_criteria'])
            for criterion in criteria:
                report += f"- {criterion}\n"
        else:
            report += "No acceptance criteria defined\n"
        
        # Get linked requirements
        cur.execute("""
            SELECT r.id, r.title FROM requirements r
            JOIN requirement_tasks rt ON r.id = rt.requirement_id
            WHERE rt.task_id = ?
        """, (params["task_id"],))
        requirements = cur.fetchall()
        
        if requirements:
            report += f"\n## Linked Requirements ({len(requirements)})\n"
            for req in requirements:
                report += f"- {req['id']}: {req['title']}\n"
        
        return [TextContent(type="text", text=report)]
        
    finally:
        conn.close()

async def handle_query_tasks(**params) -> List[TextContent]:
    """Query tasks with filters"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    query = "SELECT * FROM tasks WHERE 1=1"
    query_params = []
    
    if params.get("status"):
        query += " AND status = ?"
        query_params.append(params["status"])
    
    if params.get("priority"):
        query += " AND priority = ?"
        query_params.append(params["priority"])
    
    if params.get("assignee"):
        query += " AND assignee = ?"
        query_params.append(params["assignee"])
    
    if params.get("requirement_id"):
        query = """
            SELECT t.* FROM tasks t
            JOIN requirement_tasks rt ON t.id = rt.task_id
            WHERE rt.requirement_id = ?
        """
        query_params = [params["requirement_id"]]
    
    query += " ORDER BY priority, created_at DESC"
    
    cur.execute(query, query_params)
    tasks = cur.fetchall()
    
    if not tasks:
        return [TextContent(type="text", text="No tasks found matching criteria")]
    
    result = f"Found {len(tasks)} tasks:\n\n"
    for task in tasks:
        result += f"- {task['id']}: {task['title']} [{task['status']}] {task['priority']}"
        if task['assignee']:
            result += f" (Assigned: {task['assignee']})"
        result += "\n"
    
    return [TextContent(type="text", text=result)]

async def handle_update_architecture_status(**params) -> List[TextContent]:
    """Update architecture decision status"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Get current status
        cur.execute("SELECT status FROM architecture WHERE id = ?", (params["architecture_id"],))
        current = cur.fetchone()
        if not current:
            return [TextContent(type="text", text="Architecture decision not found")]
        
        current_status = current[0]
        new_status = params["new_status"]
        
        # Update status
        cur.execute("""
            UPDATE architecture 
            SET status = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (new_status, params["architecture_id"]))
        
        # Add review comment if provided
        if params.get("comment"):
            cur.execute("""
                INSERT INTO reviews (entity_type, entity_id, reviewer, comment)
                VALUES ('architecture', ?, 'MCP User', ?)
            """, (params["architecture_id"], params["comment"]))
        
        conn.commit()
        
        return [TextContent(
            type="text",
            text=f"Updated {params['architecture_id']} from {current_status} to {new_status}"
        )]
        
    except Exception as e:
        conn.rollback()
        return [TextContent(type="text", text=f"Error updating architecture status: {str(e)}")]
    finally:
        conn.close()

async def handle_query_architecture_decisions(**params) -> List[TextContent]:
    """Query architecture decisions with filters"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    query = "SELECT * FROM architecture WHERE 1=1"
    query_params = []
    
    if params.get("status"):
        query += " AND status = ?"
        query_params.append(params["status"])
    
    if params.get("type"):
        query += " AND type = ?"
        query_params.append(params["type"])
    
    if params.get("requirement_id"):
        query = """
            SELECT a.* FROM architecture a
            JOIN requirement_architecture ra ON a.id = ra.architecture_id
            WHERE ra.requirement_id = ?
        """
        query_params = [params["requirement_id"]]
    
    if params.get("search_text"):
        if params.get("requirement_id"):
            query += " AND (a.title LIKE ? OR a.context LIKE ?)"
        else:
            query += " AND (title LIKE ? OR context LIKE ?)"
        search = f"%{params['search_text']}%"
        query_params.extend([search, search])
    
    query += " ORDER BY created_at DESC"
    
    cur.execute(query, query_params)
    decisions = cur.fetchall()
    
    if not decisions:
        return [TextContent(type="text", text="No architecture decisions found matching criteria")]
    
    result = f"Found {len(decisions)} architecture decisions:\n\n"
    for decision in decisions:
        result += f"- {decision['id']}: {decision['title']} [{decision['status']}] ({decision['type']})\n"
    
    return [TextContent(type="text", text=result)]

async def handle_get_architecture_details(**params) -> List[TextContent]:
    """Get full architecture decision details"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    try:
        # Get architecture decision
        cur.execute("SELECT * FROM architecture WHERE id = ?", (params["architecture_id"],))
        arch = cur.fetchone()
        if not arch:
            return [TextContent(type="text", text="Architecture decision not found")]
        
        # Build detailed report
        report = f"""# Architecture Decision: {arch['id']}

## Basic Information
- **Title**: {arch['title']}
- **Type**: {arch['type']}
- **Status**: {arch['status']}
- **Created**: {arch['created_at']}
- **Updated**: {arch['updated_at']}
- **Authors**: {arch['authors'] or 'Not specified'}

## Context
{arch['context']}

## Decision
{arch['decision_outcome']}
"""
        
        if arch['decision_drivers']:
            drivers = json.loads(arch['decision_drivers'])
            report += "\n## Decision Drivers\n"
            for driver in drivers:
                report += f"- {driver}\n"
        
        if arch['considered_options']:
            options = json.loads(arch['considered_options'])
            report += "\n## Considered Options\n"
            for option in options:
                report += f"- {option}\n"
        
        if arch['consequences']:
            consequences = json.loads(arch['consequences'])
            report += "\n## Consequences\n"
            if isinstance(consequences, dict):
                for key, value in consequences.items():
                    report += f"**{key.title()}**: {value}\n"
            else:
                report += f"{consequences}\n"
        
        # Get linked requirements
        cur.execute("""
            SELECT r.id, r.title FROM requirements r
            JOIN requirement_architecture ra ON r.id = ra.requirement_id
            WHERE ra.architecture_id = ?
        """, (params["architecture_id"],))
        requirements = cur.fetchall()
        
        if requirements:
            report += f"\n## Linked Requirements ({len(requirements)})\n"
            for req in requirements:
                report += f"- {req['id']}: {req['title']}\n"
        
        # Get reviews
        cur.execute("""
            SELECT reviewer, comment, created_at FROM reviews
            WHERE entity_type = 'architecture' AND entity_id = ?
            ORDER BY created_at DESC
        """, (params["architecture_id"],))
        reviews = cur.fetchall()
        
        if reviews:
            report += f"\n## Reviews ({len(reviews)})\n"
            for review in reviews:
                report += f"- **{review['reviewer']}** ({review['created_at']}): {review['comment']}\n"
        
        return [TextContent(type="text", text=report)]
        
    finally:
        conn.close()

async def handle_add_architecture_review(**params) -> List[TextContent]:
    """Add review comment to architecture decision"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Verify architecture exists
        cur.execute("SELECT id FROM architecture WHERE id = ?", (params["architecture_id"],))
        if not cur.fetchone():
            return [TextContent(type="text", text="Architecture decision not found")]
        
        # Add review
        cur.execute("""
            INSERT INTO reviews (entity_type, entity_id, reviewer, comment)
            VALUES ('architecture', ?, ?, ?)
        """, (params["architecture_id"], params.get("reviewer", "MCP User"), params["comment"]))
        
        conn.commit()
        
        return [TextContent(
            type="text",
            text=f"Added review to {params['architecture_id']}"
        )]
        
    except Exception as e:
        conn.rollback()
        return [TextContent(type="text", text=f"Error adding review: {str(e)}")]
    finally:
        conn.close()

# Interview session storage (in-memory for simplicity)
interview_sessions = {}

async def handle_start_requirement_interview(**params) -> List[TextContent]:
    """Start interactive requirement gathering interview"""
    import uuid
    
    session_id = str(uuid.uuid4())[:8]
    
    # Initialize interview session
    interview_sessions[session_id] = {
        "project_context": params.get("project_context", ""),
        "stakeholder_role": params.get("stakeholder_role", ""),
        "gathered_data": {},
        "current_stage": "problem_identification",
        "questions_asked": []
    }
    
    # Determine first questions based on context
    questions = []
    if params.get("project_context"):
        questions.append("What specific problem or opportunity are you trying to address in this project?")
        questions.append("Who would be most impacted if this problem isn't solved?")
    else:
        questions.append("Can you describe the project or system you're working on?")
        questions.append("What's the main challenge you're facing that requires this new requirement?")
    
    interview_sessions[session_id]["current_questions"] = questions
    
    response = f"""# Requirement Interview Started
**Session ID**: {session_id}

## Context
- **Project**: {params.get('project_context', 'Not specified')}
- **Your Role**: {params.get('stakeholder_role', 'Not specified')}

## Next Questions
Please answer these questions to help gather your requirement:

"""
    
    for i, question in enumerate(questions, 1):
        response += f"{i}. {question}\n"
    
    response += "\nOnce you answer these, use `continue_requirement_interview` with your session ID and answers."
    
    return [TextContent(type="text", text=response)]

async def handle_continue_requirement_interview(**params) -> List[TextContent]:
    """Continue requirement interview with answers"""
    session_id = params["session_id"]
    answers = params["answers"]
    
    if session_id not in interview_sessions:
        return [TextContent(type="text", text="Interview session not found or expired")]
    
    session = interview_sessions[session_id]
    
    # Store answers
    for key, value in answers.items():
        session["gathered_data"][key] = value
    
    # Move to next stage based on current progress
    current_stage = session["current_stage"]
    next_questions = []
    
    if current_stage == "problem_identification":
        session["current_stage"] = "solution_definition"
        next_questions = [
            "What would success look like once this requirement is implemented?",
            "Are there any specific constraints or limitations we need to consider?"
        ]
    
    elif current_stage == "solution_definition":
        session["current_stage"] = "details_gathering"
        next_questions = [
            "What priority would you assign to this requirement (P0=Critical, P1=High, P2=Medium, P3=Low)?",
            "What type of requirement is this (FUNC=Functional, NFUNC=Non-functional, TECH=Technical, BUS=Business, INTF=Interface)?"
        ]
    
    elif current_stage == "details_gathering":
        session["current_stage"] = "validation"
        next_questions = [
            "How will we know this requirement has been successfully implemented?",
            "What are the acceptance criteria that must be met?"
        ]
    
    elif current_stage == "validation":
        # Interview complete - generate requirement
        return await complete_requirement_interview(session_id)
    
    session["current_questions"] = next_questions
    
    response = f"""# Interview Progress - Session {session_id}

## Your Previous Answers Recorded ✓

## Next Questions
"""
    
    for i, question in enumerate(next_questions, 1):
        response += f"{i}. {question}\n"
    
    response += f"\nStage: {session['current_stage'].replace('_', ' ').title()}"
    response += "\nContinue with `continue_requirement_interview` and your answers."
    
    return [TextContent(type="text", text=response)]

async def complete_requirement_interview(session_id: str) -> List[TextContent]:
    """Complete interview and create requirement"""
    session = interview_sessions[session_id]
    data = session["gathered_data"]
    
    # Map interview data to requirement fields
    requirement_data = {
        "type": data.get("requirement_type", "FUNC"),
        "title": data.get("title", "Requirement from Interview"),
        "priority": data.get("priority", "P2"),
        "current_state": data.get("current_problem", "Current state not specified"),
        "desired_state": data.get("desired_outcome", "Desired state not specified"),
        "business_value": data.get("success_criteria", ""),
        "acceptance_criteria": data.get("acceptance_criteria", "").split("\n") if data.get("acceptance_criteria") else [],
        "author": f"Interview Session {session_id}"
    }
    
    # Create the requirement
    try:
        result = await handle_create_requirement(**requirement_data)
        
        # Clean up session
        del interview_sessions[session_id]
        
        interview_summary = f"""# Interview Complete! 

## Requirement Created
{result[0].text}

## Interview Summary
- **Problem Identified**: {data.get('current_problem', 'Not specified')}
- **Solution Desired**: {data.get('desired_outcome', 'Not specified')}
- **Success Criteria**: {data.get('success_criteria', 'Not specified')}
- **Priority**: {data.get('priority', 'P2')}
- **Type**: {data.get('requirement_type', 'FUNC')}

You can now use other tools to further develop this requirement, create tasks, or add architecture decisions.
"""
        
        return [TextContent(type="text", text=interview_summary)]
        
    except Exception as e:
        return [TextContent(type="text", text=f"Error creating requirement: {str(e)}")]

async def amain():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, 
            write_stream, 
            server.create_initialization_options()
        )

def main():
    """Entry point for the lifecycle-mcp command"""
    import asyncio
    asyncio.run(amain())

if __name__ == "__main__":
    main()