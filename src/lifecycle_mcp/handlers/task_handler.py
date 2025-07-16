#!/usr/bin/env python3
"""
Task Handler for MCP Lifecycle Management Server
Handles all task-related operations
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from mcp.types import TextContent

from ..github_utils import GitHubUtils
from .base_handler import BaseHandler


class TaskHandler(BaseHandler):
    """Handler for task-related MCP tools"""

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return task tool definitions"""
        return [
            {
                "name": "create_task",
                "description": "Create implementation task from requirement",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "requirement_ids": {"type": "array", "items": {"type": "string"}},
                        "title": {"type": "string"},
                        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                        "effort": {"type": "string", "enum": ["XS", "S", "M", "L", "XL"]},
                        "user_story": {"type": "string"},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        "parent_task_id": {"type": "string"},
                        "assignee": {"type": "string"},
                    },
                    "required": ["requirement_ids", "title", "priority"],
                },
            },
            {
                "name": "update_task_status",
                "description": "Update task progress",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "new_status": {
                            "type": "string",
                            "enum": ["Not Started", "In Progress", "Blocked", "Complete", "Abandoned"],
                        },
                        "comment": {"type": "string"},
                        "assignee": {"type": "string"},
                    },
                    "required": ["task_id", "new_status"],
                },
            },
            {
                "name": "query_tasks",
                "description": "Search and filter tasks",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "priority": {"type": "string"},
                        "assignee": {"type": "string"},
                        "requirement_id": {"type": "string"},
                    },
                },
            },
            {
                "name": "get_task_details",
                "description": "Get full task details with dependencies",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
            {
                "name": "sync_task_from_github",
                "description": "Sync individual task from GitHub issue changes",
                "inputSchema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
            {
                "name": "bulk_sync_github_tasks",
                "description": "Sync all tasks with their GitHub issues",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "create_task":
                return await self._create_task(**arguments)
            elif tool_name == "update_task_status":
                return await self._update_task_status(**arguments)
            elif tool_name == "query_tasks":
                return await self._query_tasks(**arguments)
            elif tool_name == "get_task_details":
                return await self._get_task_details(**arguments)
            elif tool_name == "sync_task_from_github":
                task_id = arguments.get("task_id", "")
                if not task_id:
                    return self._create_error_response("task_id parameter required")
                return await self._sync_from_github(task_id)
            elif tool_name == "bulk_sync_github_tasks":
                return await self._bulk_sync_with_github(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    async def _create_task(self, **params) -> List[TextContent]:
        """Create task linked to requirements"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_ids", "title", "priority"])
        if error:
            return self._create_error_response(error)

        # Validate requirement approval status
        approved_statuses = {"Approved", "Architecture", "Ready", "Implemented", "Validated"}
        unapproved_reqs = []

        for req_id in params["requirement_ids"]:
            req_status = self.db.get_records("requirements", "status", "id = ?", [req_id])

            if not req_status:
                return self._create_error_response(f"Requirement {req_id} not found")

            status = req_status[0]["status"]
            if status not in approved_statuses:
                unapproved_reqs.append(f"{req_id} (status: {status})")

        if unapproved_reqs:
            error_msg = (
                "Cannot create tasks for unapproved requirements. The following requirements must be approved first:\n"
            )
            error_msg += "\n".join(f"- {req}" for req in unapproved_reqs)
            error_msg += "\n\nRequirements must be in one of these states: " + ", ".join(sorted(approved_statuses))
            return self._create_error_response(error_msg)

        try:
            # Get next task number
            task_number = self.db.get_next_id("tasks", "task_number")

            # Determine subtask number
            subtask_number = 0
            if params.get("parent_task_id"):
                # For subtasks, find the parent's task number and get next subtask number
                parent_info = self.db.get_records("tasks", "task_number", "id = ?", [params["parent_task_id"]])

                if parent_info:
                    parent_task_number = parent_info[0]["task_number"]
                    subtask_number = self.db.get_next_id(
                        "tasks", "subtask_number", "parent_task_id = ?", [params["parent_task_id"]]
                    )
                    task_number = parent_task_number
                else:
                    # Parent task not found
                    return self._create_error_response(f"Parent task {params['parent_task_id']} not found")

            task_id = f"TASK-{task_number:04d}-{subtask_number:02d}-00"

            # Prepare task data
            task_data = {
                "id": task_id,
                "task_number": task_number,
                "subtask_number": subtask_number,
                "version": 0,
                "title": params["title"],
                "priority": params["priority"],
                "effort": params.get("effort"),
                "user_story": params.get("user_story"),
                "acceptance_criteria": self._safe_json_dumps(params.get("acceptance_criteria", [])),
                "parent_task_id": params.get("parent_task_id"),
                "assignee": params.get("assignee"),
                "status": "Not Started",
            }

            # Insert task
            self.db.insert_record("tasks", task_data)

            # Link to requirements
            for req_id in params["requirement_ids"]:
                self.db.insert_record("requirement_tasks", {"requirement_id": req_id, "task_id": task_id})

            # Create GitHub issue if available
            github_url = None
            github_error = None
            if GitHubUtils.is_github_available():
                try:
                    github_title = f"{task_id}: {params['title']}"
                    github_body = GitHubUtils.format_task_body(task_data)

                    # Create labels based on priority and status
                    labels = [params["priority"].lower()]
                    if params.get("effort"):
                        labels.append(f"effort-{params['effort'].lower()}")

                    github_url = await GitHubUtils.create_github_issue(
                        title=github_title, body=github_body, labels=labels, assignee=params.get("assignee")
                    )

                    # Store GitHub issue metadata if created successfully
                    if github_url:
                        issue_number = GitHubUtils.extract_issue_number_from_url(github_url)
                        if issue_number:
                            # Get the created issue details for ETag storage
                            github_issue = await GitHubUtils.get_github_issue(issue_number)

                            github_data = {
                                "github_issue_number": issue_number,
                                "github_issue_url": github_url,
                                "github_last_sync": datetime.now(timezone.utc).isoformat(),
                                "github_etag": github_issue.get("etag") if github_issue else None,
                            }

                            self.db.update_record("tasks", github_data, "id = ?", [task_id])
                            
                            # Link to parent GitHub issue if this is a subtask
                            if params.get("parent_task_id"):
                                try:
                                    parent_info = self.db.get_records("tasks", "github_issue_number", "id = ?", [params["parent_task_id"]])
                                    if parent_info and parent_info[0].get("github_issue_number"):
                                        parent_issue_number = str(parent_info[0]["github_issue_number"])
                                        
                                        # Create parent-child relationship in GitHub
                                        success, error_msg = await GitHubUtils.create_sub_issue_relationship(
                                            parent_issue_number, issue_number
                                        )
                                        
                                        if success:
                                            self.logger.info(f"Created GitHub parent-child link: #{parent_issue_number} -> #{issue_number}")
                                        else:
                                            self.logger.warning(f"Failed to create GitHub parent-child link: {error_msg}")
                                            
                                except Exception as e:
                                    self.logger.warning(f"Error linking parent-child GitHub issues: {e}")
                    else:
                        github_error = "GitHub issue creation returned no URL"

                except Exception as e:
                    github_error = f"GitHub issue creation failed: {str(e)}"
                    self.logger.warning(f"GitHub integration error for task {task_id}: {github_error}")
            else:
                github_error = "GitHub not available or not configured"

            # Create above-the-fold response
            key_info = f"Task {task_id} created"
            action_info = f"📋 {params['title']} | {params['priority']} | {params.get('effort', 'No effort specified')}"

            github_info = ""
            if github_url:
                github_info = f"🔗 GitHub: {github_url}"
            elif github_error:
                github_info = f"⚠️ GitHub: {github_error}"

            return self._create_above_fold_response("SUCCESS", key_info, action_info, github_info)

        except Exception as e:
            return self._create_error_response("Failed to create task", e)

    async def _update_task_status(self, **params) -> List[TextContent]:
        """Update task status"""
        # Validate required parameters
        error = self._validate_required_params(params, ["task_id", "new_status"])
        if error:
            return self._create_error_response(error)

        try:
            # Get current task with GitHub info
            current_tasks = self.db.get_records(
                "tasks", "status, assignee, github_issue_number, github_issue_url", "id = ?", [params["task_id"]]
            )

            if not current_tasks:
                return self._create_error_response("Task not found")

            current_task = dict(current_tasks[0])  # Convert Row to dict for .get() method
            current_status = current_task["status"]
            new_status = params["new_status"]

            # Prepare update data
            update_data = {"status": new_status, "updated_at": "CURRENT_TIMESTAMP"}

            if params.get("assignee"):
                update_data["assignee"] = params["assignee"]

            # Update task
            self.db.update_record("tasks", update_data, "id = ?", [params["task_id"]])

            # Add comment if provided
            if params.get("comment"):
                self._add_review_comment("task", params["task_id"], params["comment"])

            # Update GitHub issue if it exists using sync-safe operations
            github_updated = False
            github_error = None

            if current_task.get("github_issue_number") and GitHubUtils.is_github_available():
                try:
                    # Prepare GitHub updates
                    github_updates = {}

                    # Map task status to GitHub state
                    if new_status == "Complete":
                        github_updates["state"] = "closed"
                    elif new_status in ["Not Started", "In Progress", "Blocked"]:
                        github_updates["state"] = "open"

                    # Prepare comment
                    github_comment = f"Task status updated from '{current_status}' to '{new_status}'"
                    if params.get("comment"):
                        github_comment += f"\n\n{params['comment']}"
                    github_updates["comment"] = github_comment

                    # Update assignee if changed
                    if params.get("assignee") and params["assignee"] != current_task.get("assignee"):
                        github_updates["assignees"] = [params["assignee"]] if params["assignee"] else []

                    # Use sync-safe update without ETag (force update from MCP side)
                    success, error_msg, updated_issue = await GitHubUtils.update_github_issue_safe(
                        str(current_task["github_issue_number"]), github_updates, expected_etag=None
                    )

                    if success and updated_issue:
                        github_updated = True
                        # Update stored ETag and sync timestamp
                        self.db.update_record(
                            "tasks",
                            {"github_etag": updated_issue.get("etag"), "github_last_sync": datetime.now().isoformat()},
                            "id = ?",
                            [params["task_id"]],
                        )
                    else:
                        github_error = error_msg or "GitHub update failed"
                        self.logger.warning(f"GitHub sync failed for task {params['task_id']}: {github_error}")

                except Exception as e:
                    github_error = f"GitHub update error: {str(e)}"
                    self.logger.error(f"GitHub integration error: {github_error}")
            else:
                if current_task.get("github_issue_number"):
                    github_error = "GitHub not available"

            # Create above-the-fold response
            key_info = f"Task {params['task_id']} updated"
            action_info = f"📈 {current_status} → {new_status}"

            github_info = ""
            if github_updated:
                github_info = f"🔗 GitHub issue #{current_task['github_issue_number']} synced"
            elif github_error:
                github_info = f"⚠️ GitHub sync failed: {github_error}"

            return self._create_above_fold_response("SUCCESS", key_info, action_info, github_info)

        except Exception as e:
            return self._create_error_response("Failed to update task", e)

    async def _query_tasks(self, **params) -> List[TextContent]:
        """Query tasks with filters"""
        # DEBUG: Log when this method is actually called
        print(f"DEBUG: _query_tasks called with params: {params}")
        try:
            where_clauses = []
            where_params = []

            # Handle requirement_id filter specially (requires join)
            if params.get("requirement_id"):
                tasks = self.db.execute_query(
                    """
                    SELECT t.* FROM tasks t
                    JOIN requirement_tasks rt ON t.id = rt.task_id
                    WHERE rt.requirement_id = ?
                    ORDER BY t.priority, t.created_at DESC
                """,
                    [params["requirement_id"]],
                    fetch_all=True,
                    row_factory=True,
                )
            else:
                # Build standard filters
                if params.get("status"):
                    where_clauses.append("status = ?")
                    where_params.append(params["status"])

                if params.get("priority"):
                    where_clauses.append("priority = ?")
                    where_params.append(params["priority"])

                if params.get("assignee"):
                    where_clauses.append("assignee = ?")
                    where_params.append(params["assignee"])

                where_clause = " AND ".join(where_clauses) if where_clauses else ""

                tasks = self.db.get_records("tasks", "*", where_clause, where_params, "priority, created_at DESC")

            if not tasks:
                return self._create_above_fold_response("INFO", "No tasks found", "Try adjusting search criteria")

            # Build filter description for above-the-fold
            filters = []
            if params.get("status"):
                filters.append(f"status: {params['status']}")
            if params.get("priority"):
                filters.append(f"priority: {params['priority']}")
            if params.get("assignee"):
                filters.append(f"assignee: {params['assignee']}")
            filter_desc = " | ".join(filters) if filters else "all tasks"

            # Build detailed list
            task_list = []
            for task in tasks:
                task_info = f"- {task['id']}: {task['title']} [{task['status']}] {task['priority']}"
                if task["assignee"]:
                    task_info += f" (👤 {task['assignee']})"
                task_list.append(task_info)

            key_info = self._format_count_summary("task", len(tasks), filter_desc)
            details = "\n".join(task_list)

            return self._create_above_fold_response("SUCCESS", key_info, "", details)

        except Exception as e:
            return self._create_error_response("Failed to query tasks", e)

    async def _sync_from_github(self, task_id: str) -> List[TextContent]:
        """Sync task from GitHub issue changes"""
        # Check if GitHub integration is available/enabled
        if not GitHubUtils.is_github_available():
            return self._create_above_fold_response(
                "INFO", "GitHub integration is disabled",
                "To enable GitHub sync, set GITHUB_INTEGRATION_ENABLED=true and configure GITHUB_TOKEN and GITHUB_REPO"
            )
        
        # DEBUG: Log when this method is actually called
        print(f"DEBUG: _sync_from_github called with task_id: {task_id}")
        try:
            # Get current task with GitHub info
            tasks = self.db.get_records("tasks", "*", "id = ?", [task_id])

            if not tasks:
                return self._create_error_response("Task not found")

            task = dict(tasks[0])  # Convert Row to dict for .get() method
            github_issue_number = task.get("github_issue_number")

            if not github_issue_number:
                return self._create_error_response("Task has no associated GitHub issue")

            # Use GitHubUtils sync method
            success, sync_message, github_issue = await GitHubUtils.sync_task_with_github(
                task,
                force_sync=False,  # task is already a dict
            )

            # Handle conflicts as warnings, not errors
            if not success and "conflicts detected" in sync_message.lower():
                key_info = f"Sync conflicts for task {task_id}"
                return self._create_above_fold_response("WARNING", key_info, sync_message)

            # Handle other failures as errors
            if not success:
                return self._create_error_response(f"GitHub sync failed: {sync_message}")

            # Apply GitHub changes to local task if needed
            updates_applied = []

            # Only apply updates if GitHub has newer data
            should_apply_updates = "updates available" in sync_message.lower()

            if github_issue and should_apply_updates:
                # Map GitHub state to task status
                github_state = github_issue.get("state", "")
                current_status = task.get("status", "")

                new_status = None
                if github_state == "closed" and current_status != "Complete":
                    new_status = "Complete"
                elif github_state == "open" and current_status == "Complete":
                    new_status = "In Progress"

                if new_status:
                    self.db.update_record(
                        "tasks",
                        {
                            "status": new_status,
                            "github_last_sync": datetime.now(timezone.utc).isoformat(),
                            "github_etag": github_issue.get("etag"),
                        },
                        "id = ?",
                        [task_id],
                    )
                    updates_applied.append(f"Status: {current_status} → {new_status}")

                # Update assignee if changed
                github_assignees = [a.get("login", "") for a in github_issue.get("assignees", [])]
                github_assignee = github_assignees[0] if github_assignees else None
                current_assignee = task.get("assignee")

                if github_assignee != current_assignee:
                    self.db.update_record("tasks", {"assignee": github_assignee}, "id = ?", [task_id])
                    updates_applied.append(f"Assignee: {current_assignee or 'None'} → {github_assignee or 'None'}")

                # Update title if changed (extract from GitHub title, removing task ID prefix)
                github_title = github_issue.get("title", "")
                current_title = task.get("title", "")
                
                # Remove task ID prefix from GitHub title if present
                if github_title.startswith(f"{task_id}: "):
                    clean_github_title = github_title[len(f"{task_id}: "):].strip()
                else:
                    clean_github_title = github_title
                
                if clean_github_title and clean_github_title != current_title:
                    self.db.update_record("tasks", {"title": clean_github_title}, "id = ?", [task_id])
                    updates_applied.append(f"Title updated from GitHub")

                # Update acceptance criteria if changed
                github_body = github_issue.get("body", "")
                if github_body:
                    github_ac = GitHubUtils._parse_acceptance_criteria_from_body(github_body)
                    
                    if github_ac:
                        current_ac_json = task.get("acceptance_criteria", "[]")
                        try:
                            current_ac = json.loads(current_ac_json) if current_ac_json else []
                        except json.JSONDecodeError:
                            current_ac = []
                        
                        if github_ac != current_ac:
                            self.db.update_record(
                                "tasks", 
                                {"acceptance_criteria": json.dumps(github_ac)}, 
                                "id = ?", 
                                [task_id]
                            )
                            updates_applied.append(f"Acceptance criteria updated ({len(github_ac)} items)")

                # Update the sync timestamp to mark that we've processed the GitHub changes
                if updates_applied:
                    self.db.update_record(
                        "tasks",
                        {"github_last_sync": datetime.now(timezone.utc).isoformat()},
                        "id = ?",
                        [task_id],
                    )

            # Create response
            if updates_applied:
                key_info = f"Task {task_id} synced from GitHub"
                action_info = " | ".join(updates_applied)
                return self._create_above_fold_response("SUCCESS", key_info, action_info)
            else:
                key_info = f"Task {task_id} already in sync"
                return self._create_above_fold_response("INFO", key_info, sync_message)

        except Exception as e:
            return self._create_error_response("Failed to sync from GitHub", e)

    async def _bulk_sync_with_github(self, **params) -> List[TextContent]:
        """Sync all tasks with GitHub issues"""
        # Check if GitHub integration is available/enabled
        if not GitHubUtils.is_github_available():
            return self._create_above_fold_response(
                "INFO", "GitHub integration is disabled", 
                "To enable GitHub sync, set GITHUB_INTEGRATION_ENABLED=true and configure GITHUB_TOKEN and GITHUB_REPO"
            )
        
        try:
            # Get all tasks with GitHub issues
            tasks_with_github = self.db.get_records(
                "tasks",
                "id, title, status, github_issue_number, github_last_sync",
                "github_issue_number IS NOT NULL AND github_issue_number != ''",
                [],
                "created_at DESC",
            )

            if not tasks_with_github:
                return self._create_above_fold_response("INFO", "No tasks with GitHub issues found")

            # Check sync status for each task
            sync_results = []
            conflicts_found = []
            updates_applied = []

            for task in tasks_with_github:
                try:
                    success, sync_message, github_issue = await GitHubUtils.sync_task_with_github(
                        dict(task), force_sync=False
                    )

                    if not success:
                        if "conflicts detected" in sync_message.lower():
                            conflicts_found.append(f"{dict(task)['id']}: {sync_message}")
                        else:
                            sync_results.append(f"❌ {dict(task)['id']}: {sync_message}")
                    elif "in sync" in sync_message.lower():
                        sync_results.append(f"✅ {dict(task)['id']}: {sync_message}")
                    else:
                        # Apply updates if any changes detected
                        task_updates = []
                        task_dict = dict(task)

                        if github_issue:
                            # Update status if changed
                            github_state = github_issue.get("state", "")
                            current_status = task_dict.get("status", "")

                            new_status = None
                            if github_state == "closed" and current_status != "Complete":
                                new_status = "Complete"
                            elif github_state == "open" and current_status == "Complete":
                                new_status = "In Progress"

                            update_data = {
                                "github_last_sync": datetime.now(timezone.utc).isoformat(),
                                "github_etag": github_issue.get("etag"),
                            }

                            if new_status:
                                update_data["status"] = new_status
                                task_updates.append(f"Status: {current_status} → {new_status}")

                            # Update assignee if changed
                            github_assignees = [a.get("login", "") for a in github_issue.get("assignees", [])]
                            github_assignee = github_assignees[0] if github_assignees else None
                            current_assignee = task_dict.get("assignee")

                            if github_assignee != current_assignee:
                                update_data["assignee"] = github_assignee
                                from_assignee = current_assignee or "None"
                                to_assignee = github_assignee or "None"
                                task_updates.append(f"Assignee: {from_assignee} → {to_assignee}")

                            if task_updates:
                                self.db.update_record("tasks", update_data, "id = ?", [task_dict["id"]])
                                updates_applied.append(f"🔄 {task_dict['id']}: {' | '.join(task_updates)}")
                            else:
                                sync_results.append(f"✅ {task_dict['id']}: Updated sync metadata")

                except Exception as e:
                    sync_results.append(f"❌ {dict(task)['id']}: Error - {str(e)}")

            # Import missing GitHub issues as tasks
            imported_issues = []
            import_errors = []
            
            try:
                # Fetch all repository issues
                all_issues = await GitHubUtils.fetch_all_repository_issues(state="all")
                
                if all_issues:
                    # Get existing task issue numbers to avoid duplicates
                    existing_issues = {str(dict(task)["github_issue_number"]) for task in tasks_with_github if dict(task).get("github_issue_number")}
                    
                    # Find issues that don't have corresponding tasks
                    missing_issues = [
                        issue for issue in all_issues 
                        if str(issue.get("number", "")) not in existing_issues
                    ]
                    
                    # Import missing issues as tasks (limit to prevent overwhelming)
                    for issue in missing_issues[:10]:  # Limit to 10 new issues per sync
                        try:
                            # Extract basic info from issue
                            issue_number = issue.get("number")
                            title = issue.get("title", f"GitHub Issue #{issue_number}")
                            body = issue.get("body", "")
                            state = issue.get("state", "open")
                            
                            # Determine task status from GitHub state
                            task_status = "Complete" if state == "closed" else "Not Started"
                            
                            # Parse acceptance criteria from body
                            acceptance_criteria = GitHubUtils._parse_acceptance_criteria_from_body(body)
                            
                            # Generate unique task ID
                            task_number = self.db.get_next_sequence_number("tasks")
                            task_id = f"TASK-{task_number:04d}-00-00"
                            
                            # Create task data
                            task_data = {
                                "id": task_id,
                                "task_number": task_number,
                                "version": "00-00",
                                "title": title,
                                "status": task_status,
                                "priority": "P2",  # Default priority for imported issues
                                "effort": "S",     # Default effort for imported issues
                                "user_story": f"Imported from GitHub Issue #{issue_number}",
                                "acceptance_criteria": json.dumps(acceptance_criteria),
                                "github_issue_number": str(issue_number),
                                "github_issue_url": issue.get("url", ""),
                                "github_last_sync": datetime.now(timezone.utc).isoformat(),
                                "github_etag": issue.get("etag", ""),
                                "created_at": datetime.now(timezone.utc).isoformat(),
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                            
                            # Insert task
                            self.db.insert_record("tasks", task_data)
                            imported_issues.append(f"✅ {task_id}: {title} (Issue #{issue_number})")
                            
                        except Exception as e:
                            import_errors.append(f"❌ Issue #{issue.get('number', 'unknown')}: {str(e)}")
                            
            except Exception as e:
                import_errors.append(f"❌ Issue import failed: {str(e)}")

            # Sync from GitHub project board to lifecycle statuses
            project_sync_results = []
            project_sync_errors = []
            project_updates_applied = []
            
            try:
                project_updated_count, project_error_count, project_messages = await GitHubUtils.sync_from_project_board(
                    [dict(task) for task in tasks_with_github]
                )
                
                # Process status changes from project board
                for message in project_messages:
                    if isinstance(message, dict) and message.get("type") == "status_change":
                        try:
                            task_id = message["task_id"]
                            current_status = message["current_status"]
                            target_status = message["target_status"]
                            project_status = message["project_status"]
                            
                            # Update task status in database
                            update_data = {
                                "status": target_status,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                                "github_last_sync": datetime.now(timezone.utc).isoformat()
                            }
                            
                            self.db.update_record("tasks", update_data, "id = ?", [task_id])
                            project_updates_applied.append(
                                f"🔄 {task_id}: {current_status} → {target_status} (from project: {project_status})"
                            )
                            
                        except Exception as e:
                            project_sync_errors.append(f"❌ {task_id}: Failed to update status - {str(e)}")
                    elif isinstance(message, str):
                        project_sync_errors.append(message)
                
                if project_updates_applied:
                    project_sync_results.append(f"✅ {len(project_updates_applied)} tasks updated from project board")
                    
            except Exception as e:
                project_sync_errors.append(f"❌ Project board sync failed: {str(e)}")

            # Build summary
            total_tasks = len(tasks_with_github)
            updates_count = len(updates_applied)
            conflicts_count = len(conflicts_found)
            imported_count = len(imported_issues)
            project_updates_count = len(project_updates_applied)

            key_info = f"Synced {total_tasks} GitHub task(s)"
            action_info = f"🔄 {updates_count} updated | 📋 {project_updates_count} from project | ⚠️ {conflicts_count} conflicts | 📥 {imported_count} imported"

            # Build detailed report
            details = []
            if updates_applied:
                details.append("## Updated Tasks (from GitHub issues)")
                details.extend(updates_applied)
                details.append("")

            if project_updates_applied:
                details.append("## Updated Tasks (from project board)")
                details.extend(project_updates_applied)
                details.append("")

            if project_sync_results:
                details.append("## Project Board Sync Results")
                details.extend(project_sync_results)
                details.append("")

            if project_sync_errors:
                details.append("## Project Board Sync Errors")
                details.extend(project_sync_errors)
                details.append("")

            if imported_issues:
                details.append("## Imported GitHub Issues")
                details.extend(imported_issues)
                details.append("")

            if import_errors:
                details.append("## Import Errors")
                details.extend(import_errors)
                details.append("")

            if conflicts_found:
                details.append("## Conflicts Detected")
                details.extend(conflicts_found)
                details.append("")

            if sync_results:
                details.append("## All Sync Results")
                details.extend(sync_results)

            report = "\n".join(details)

            return self._create_above_fold_response("SUCCESS", key_info, action_info, report)

        except Exception as e:
            return self._create_error_response("Failed to bulk sync with GitHub", e)

    async def _get_task_details(self, **params) -> List[TextContent]:
        """Get full task details"""
        # Validate required parameters
        error = self._validate_required_params(params, ["task_id"])
        if error:
            return self._create_error_response(error)

        try:
            # Get task
            tasks = self.db.get_records("tasks", "*", "id = ?", [params["task_id"]])

            if not tasks:
                return self._create_error_response("Task not found")

            task = dict(tasks[0])  # Convert Row to dict for .get() method

            # Build report
            task_info = f"""# Task Details: {task["id"]}

## Basic Information
- **Title**: {task["title"]}
- **Status**: {task["status"]}
- **Priority**: {task["priority"]}
- **Effort**: {task["effort"] or "Not specified"}
- **Assignee**: {task["assignee"] or "Unassigned"}
- **Created**: {task["created_at"]}
- **Updated**: {task["updated_at"]}"""

            if task["github_issue_number"]:
                task_info += f"\n- **GitHub Issue**: #{task['github_issue_number']} - {task['github_issue_url']}"

            task_info += f"""

## Description
{task["user_story"] or "No user story provided"}

## Acceptance Criteria
"""

            if task["acceptance_criteria"]:
                criteria = self._safe_json_loads(task["acceptance_criteria"])
                if criteria:
                    for criterion in criteria:
                        task_info += f"- {criterion}\n"
                else:
                    task_info += "No acceptance criteria defined\n"
            else:
                task_info += "No acceptance criteria defined\n"

            # Get linked requirements
            requirements = self.db.execute_query(
                """
                SELECT r.id, r.title FROM requirements r
                JOIN requirement_tasks rt ON r.id = rt.requirement_id
                WHERE rt.task_id = ?
            """,
                [params["task_id"]],
                fetch_all=True,
                row_factory=True,
            )

            if requirements:
                task_info += f"\n## Linked Requirements ({len(requirements)})\n"
                for req in requirements:
                    task_info += f"- {req['id']}: {req['title']}\n"

            # Get subtasks if this is a parent task
            subtasks = self.db.get_records(
                "tasks", "id, title, status", "parent_task_id = ?", [params["task_id"]], "subtask_number"
            )

            if subtasks:
                task_info += f"\n## Subtasks ({len(subtasks)})\n"
                for subtask in subtasks:
                    task_info += f"- {subtask['id']}: {subtask['title']} [{subtask['status']}]\n"

            # Show parent task if this is a subtask
            if task["parent_task_id"]:
                parent_tasks = self.db.get_records("tasks", "id, title, status", "id = ?", [task["parent_task_id"]])

                if parent_tasks:
                    parent = dict(parent_tasks[0])  # Convert Row to dict for consistency
                    task_info += "\n## Parent Task\n"
                    task_info += f"- {parent['id']}: {parent['title']} [{parent['status']}]\n"

            # Create above-the-fold summary
            key_info = self._format_status_summary("Task", task["id"], task["status"])
            action_info = f"📋 {task['title']} | {task['priority']} | {task['effort'] or 'No effort'}"
            if task["assignee"]:
                action_info += f" | 👤 {task['assignee']}"

            return self._create_above_fold_response("INFO", key_info, action_info, task_info)

        except Exception as e:
            return self._create_error_response("Failed to get task details", e)
