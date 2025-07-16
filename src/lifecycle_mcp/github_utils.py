#!/usr/bin/env python3
"""
GitHub integration utilities for MCP Lifecycle Management Server
Provides GitHub CLI integration for issue management
"""

import asyncio
import json
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import config


class GitHubUtils:
    """Utilities for GitHub CLI integration"""

    @staticmethod
    def is_github_available() -> bool:
        """Check if GitHub integration is enabled and properly configured"""
        # First check if GitHub integration is enabled via configuration
        if not config.is_github_integration_enabled():
            return False
        
        # Validate configuration completeness
        is_valid, _ = config.validate_github_config()
        if not is_valid:
            return False
            
        try:
            # Check if gh CLI is available
            result = subprocess.run(["gh", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return False

            # Check if we're in a git repository
            result = subprocess.run(["git", "rev-parse", "--git-dir"], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return False

            # Check if there's a GitHub remote
            result = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return False

            # Verify the remote is a GitHub URL
            remote_url = result.stdout.strip()
            return "github.com" in remote_url

        except Exception:
            return False

    @staticmethod
    def validate_github_configuration() -> Tuple[bool, List[str]]:
        """Validate GitHub configuration and return (is_valid, error_messages)"""
        return config.validate_github_config()

    @staticmethod
    async def create_github_issue(
        title: str, body: str, labels: Optional[list] = None, assignee: Optional[str] = None
    ) -> Optional[str]:
        """Create a GitHub issue and return the issue URL"""
        if not GitHubUtils.is_github_available():
            return None

        try:
            cmd = ["gh", "issue", "create", "--title", title, "--body", body]

            if labels:
                # Filter out any labels that might not exist
                cmd.extend(["--label", ",".join(labels)])

            if assignee and assignee != "":
                cmd.extend(["--assignee", assignee])

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                issue_url = stdout.decode().strip()
                
                # Automatically add the new issue to the configured project board
                project_id = config.get_github_project_id()
                if project_id:
                    try:
                        # Get status mappings and use "Not Started" as default for new issues
                        status_mappings = config.get_status_mappings()
                        initial_status = status_mappings.get("Not Started", "Todo")
                        
                        success, error, item_data = await GitHubUtils.add_issue_to_project(
                            issue_url, project_id, initial_status
                        )
                        
                        if success:
                            print(f"Added issue to project board with status: {initial_status}")
                        else:
                            print(f"Failed to add issue to project board: {error}")
                            
                    except Exception as e:
                        print(f"Error adding issue to project board: {e}")
                
                return issue_url
            else:
                # Issue creation failed, but don't error the main operation
                print(f"GitHub issue creation failed: {stderr.decode()}")
                return None

        except Exception as e:
            print(f"Error creating GitHub issue: {e}")
            return None

    @staticmethod
    async def update_github_issue(issue_number: str, new_status: str, comment: Optional[str] = None) -> bool:
        """Update a GitHub issue status and optionally add a comment (legacy method)"""
        # Use the new sync-safe method for backward compatibility
        updates = {}

        # Map task statuses to GitHub states
        if new_status == "Complete":
            updates["state"] = "closed"
        elif new_status in ["Not Started", "In Progress", "Blocked"]:
            updates["state"] = "open"

        if comment:
            updates["comment"] = comment

        success, error_msg, _ = await GitHubUtils.update_github_issue_safe(
            issue_number, updates, expected_etag=None, retry_count=1
        )

        if not success and error_msg:
            print(f"Error updating GitHub issue: {error_msg}")

        return success

    @staticmethod
    def format_task_body(task_data: Dict[str, Any]) -> str:
        """Format task data into GitHub issue body"""
        body = f"**Status**: {task_data.get('status', 'Not Started')}\n"
        body += f"**Priority**: {task_data.get('priority', 'P2')}\n"
        body += "**Type**: Implementation Task\n\n"

        if task_data.get("user_story"):
            body += f"## Description\n{task_data['user_story']}\n\n"

        body += "## Acceptance Criteria\n"
        criteria = task_data.get("acceptance_criteria", [])
        if isinstance(criteria, str):
            try:
                criteria = json.loads(criteria)
            except Exception:
                criteria = []

        if criteria:
            for criterion in criteria:
                # Mark as completed if task is complete
                checkbox = "[x]" if task_data.get("status") == "Complete" else "[ ]"
                body += f"- {checkbox} {criterion}\n"
        else:
            body += "- [ ] Task completion criteria to be defined\n"

        body += f"\n**Task ID**: {task_data.get('id', 'TBD')}"

        return body

    @staticmethod
    def extract_issue_number_from_url(url: str) -> Optional[str]:
        """Extract issue number from GitHub issue URL"""
        try:
            # URL format: https://github.com/owner/repo/issues/123
            parts = url.split("/")
            if "issues" in parts:
                idx = parts.index("issues")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        except Exception:
            pass
        return None

    @staticmethod
    async def get_github_issue(issue_number: str) -> Optional[Dict[str, Any]]:
        """Retrieve current GitHub issue state with sync metadata"""
        if not GitHubUtils.is_github_available():
            return None

        try:
            cmd = [
                "gh",
                "issue",
                "view",
                issue_number,
                "--json",
                "number,title,body,state,assignees,labels,updatedAt,url",
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                issue_data = json.loads(stdout.decode())
                # Add sync metadata
                issue_data["sync_timestamp"] = datetime.now(timezone.utc).isoformat()
                issue_data["etag"] = GitHubUtils._generate_etag(issue_data)
                return issue_data
            else:
                print(f"Error retrieving GitHub issue: {stderr.decode()}")
                return None

        except Exception as e:
            print(f"Error getting GitHub issue: {e}")
            return None

    @staticmethod
    async def update_github_issue_safe(
        issue_number: str, updates: Dict[str, Any], expected_etag: Optional[str] = None, retry_count: int = 3
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Update GitHub issue with conflict detection and retry logic

        Returns:
            Tuple of (success, error_message, current_issue_data)
        """
        if not GitHubUtils.is_github_available():
            return False, "GitHub not available", None

        for attempt in range(retry_count):
            try:
                # Get current issue state
                current_issue = await GitHubUtils.get_github_issue(issue_number)
                if not current_issue:
                    return False, f"Issue {issue_number} not found", None

                # Check for conflicts if ETag provided
                if expected_etag and current_issue.get("etag") != expected_etag:
                    return False, "Conflict detected: Issue has been modified by another process", current_issue

                # Apply updates
                success = True
                error_msg = None

                # Update issue state (open/closed)
                if "state" in updates:
                    current_state = current_issue["state"].lower()
                    target_state = updates["state"].lower()
                    if target_state == "closed" and current_state == "open":
                        success, error_msg = await GitHubUtils._close_issue(issue_number, updates.get("comment"))
                    elif target_state == "open" and current_state == "closed":
                        success, error_msg = await GitHubUtils._reopen_issue(issue_number, updates.get("comment"))

                # Update assignees
                if "assignees" in updates and success:
                    success, error_msg = await GitHubUtils._update_assignees(issue_number, updates["assignees"])

                # Update labels
                if "labels" in updates and success:
                    success, error_msg = await GitHubUtils._update_labels(issue_number, updates["labels"])

                # Add comment if provided and no state change
                if "comment" in updates and "state" not in updates and success:
                    success, error_msg = await GitHubUtils._add_comment(issue_number, updates["comment"])

                if success:
                    # Get updated issue data
                    updated_issue = await GitHubUtils.get_github_issue(issue_number)
                    
                    # Update project board status if configured and state changed
                    if "state" in updates:
                        project_id = config.get_github_project_id()
                        if project_id and updated_issue:
                            try:
                                issue_url = updated_issue.get("url", "")
                                if issue_url:
                                    # Map the new state to project status
                                    status_mappings = config.get_status_mappings()
                                    new_state = updates["state"].lower()
                                    
                                    if new_state == "closed":
                                        project_status = status_mappings.get("Complete", "Done")
                                    else:
                                        project_status = status_mappings.get("In Progress", "In Progress")
                                    
                                    # Find the project item and update its status
                                    # Note: We'll add the issue to project if not already there
                                    add_success, add_error, item_data = await GitHubUtils.add_issue_to_project(
                                        issue_url, project_id, project_status
                                    )
                                    
                                    if add_success:
                                        print(f"Updated project board status to: {project_status}")
                                    elif "already in project" not in (add_error or "").lower():
                                        print(f"Failed to update project board: {add_error}")
                                        
                            except Exception as e:
                                print(f"Error updating project board status: {e}")
                    
                    return True, None, updated_issue
                else:
                    if attempt < retry_count - 1:
                        # Exponential backoff
                        await asyncio.sleep(2**attempt)
                        continue
                    return False, error_msg, current_issue

            except Exception as e:
                if attempt < retry_count - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                return False, f"Error updating GitHub issue: {e}", None

        return False, "Max retries exceeded", None

    @staticmethod
    async def sync_task_with_github(
        task_data: Dict[str, Any], force_sync: bool = False
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Synchronize task with its GitHub issue

        Returns:
            Tuple of (success, sync_message, github_issue_data)
        """
        github_issue_number = task_data.get("github_issue_number")
        if not github_issue_number:
            return False, "No GitHub issue associated with task", None

        try:
            # Get current GitHub issue state
            github_issue = await GitHubUtils.get_github_issue(str(github_issue_number))
            if not github_issue:
                return False, f"GitHub issue #{github_issue_number} not found", None

            # Check if sync is needed
            last_sync = task_data.get("github_last_sync")
            github_updated = github_issue.get("updatedAt")

            if not force_sync and last_sync and github_updated:
                try:
                    # Ensure both datetimes are timezone-aware for comparison
                    last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                    if last_sync_dt.tzinfo is None:
                        last_sync_dt = last_sync_dt.replace(tzinfo=timezone.utc)

                    github_updated_dt = datetime.fromisoformat(github_updated.replace("Z", "+00:00"))
                    if github_updated_dt.tzinfo is None:
                        github_updated_dt = github_updated_dt.replace(tzinfo=timezone.utc)

                    if github_updated_dt <= last_sync_dt:
                        return True, "Already in sync", github_issue
                except ValueError:
                    pass  # Continue with sync if date parsing fails

            # Detect conflicts
            conflicts = []

            # Check state conflicts
            task_status = task_data.get("status", "")
            github_state = github_issue.get("state", "").lower()

            # Check if task status and GitHub state are properly synchronized
            def are_states_synchronized(task_status: str, github_state: str) -> bool:
                """Check if task status and GitHub state are synchronized"""
                # Complete tasks should have closed issues
                if task_status == "Complete":
                    return github_state == "closed"
                # All other task statuses should have open issues
                elif task_status in ["Not Started", "In Progress", "Blocked"]:
                    return github_state == "open"
                # Unknown task status - consider it a conflict
                return False

            if not are_states_synchronized(task_status, github_state):
                conflicts.append(f"Status mismatch: Task={task_status}, GitHub={github_state}")

            # Check assignee conflicts
            task_assignee = task_data.get("assignee") or ""
            github_assignees = [a.get("login", "") for a in github_issue.get("assignees", [])]
            github_assignee = github_assignees[0] if github_assignees else ""

            # Only report assignee conflicts if there's an actual difference (not None vs "")
            if task_assignee != github_assignee and not (not task_assignee and not github_assignee):
                conflicts.append(f"Assignee mismatch: Task={task_assignee}, GitHub={github_assignee}")

            if conflicts:
                conflict_msg = "Sync conflicts detected:\n" + "\n".join(f"- {c}" for c in conflicts)
                return False, conflict_msg, github_issue

            # Check if GitHub was updated after last sync (indicating potential updates needed)
            if last_sync and github_updated:
                try:
                    last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                    if last_sync_dt.tzinfo is None:
                        last_sync_dt = last_sync_dt.replace(tzinfo=timezone.utc)

                    github_updated_dt = datetime.fromisoformat(github_updated.replace("Z", "+00:00"))
                    if github_updated_dt.tzinfo is None:
                        github_updated_dt = github_updated_dt.replace(tzinfo=timezone.utc)

                    if github_updated_dt > last_sync_dt:
                        return True, "Updates available from GitHub", github_issue
                except ValueError:
                    pass  # Continue with standard sync check

            return True, "In sync", github_issue

        except Exception as e:
            return False, f"Error syncing with GitHub: {e}", None

    @staticmethod
    def _parse_acceptance_criteria_from_body(body: str) -> List[str]:
        """Parse acceptance criteria from GitHub issue body"""
        if not body:
            return []
        
        criteria = []
        lines = body.split('\n')
        in_ac_section = False
        
        for line in lines:
            line = line.strip()
            
            # Look for acceptance criteria section
            if line.lower().startswith('## acceptance criteria'):
                in_ac_section = True
                continue
            
            # Stop at next section
            if in_ac_section and line.startswith('##'):
                break
            
            # Extract criteria items
            if in_ac_section:
                # Handle both checkbox format and bullet format
                if line.startswith('- [ ]') or line.startswith('- [x]'):
                    # Checkbox format: - [ ] Criterion text
                    criterion = line[5:].strip()  # Remove "- [ ]" or "- [x]"
                    if criterion:
                        criteria.append(criterion)
                elif line.startswith('-'):
                    # Bullet format: - Criterion text
                    criterion = line[1:].strip()  # Remove "-"
                    if criterion:
                        criteria.append(criterion)
        
        return criteria
    
    @staticmethod
    def _generate_etag(issue_data: Dict[str, Any]) -> str:
        """Generate ETag from issue data for conflict detection"""
        # Use updatedAt + state + assignees as the basis for ETag
        key_fields = {
            "updatedAt": issue_data.get("updatedAt", ""),
            "state": issue_data.get("state", ""),
            "assignees": [a.get("login", "") for a in issue_data.get("assignees", [])],
            "labels": [label.get("name", "") for label in issue_data.get("labels", [])],
        }
        return str(hash(json.dumps(key_fields, sort_keys=True)))

    @staticmethod
    async def _close_issue(issue_number: str, comment: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Close GitHub issue with optional comment"""
        try:
            cmd = ["gh", "issue", "close", issue_number]
            if comment:
                cmd.extend(["--comment", comment])

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return True, None
            else:
                return False, stderr.decode().strip()
        except Exception as e:
            return False, str(e)

    @staticmethod
    async def _reopen_issue(issue_number: str, comment: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Reopen GitHub issue with optional comment"""
        try:
            cmd = ["gh", "issue", "reopen", issue_number]
            if comment:
                cmd.extend(["--comment", comment])

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return True, None
            else:
                return False, stderr.decode().strip()
        except Exception as e:
            return False, str(e)

    @staticmethod
    async def _add_comment(issue_number: str, comment: str) -> Tuple[bool, Optional[str]]:
        """Add comment to GitHub issue"""
        try:
            process = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "comment",
                issue_number,
                "--body",
                comment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return True, None
            else:
                return False, stderr.decode().strip()
        except Exception as e:
            return False, str(e)

    @staticmethod
    async def _update_assignees(issue_number: str, assignees: List[str]) -> Tuple[bool, Optional[str]]:
        """Update GitHub issue assignees"""
        try:
            # GitHub CLI requires specific format for multiple assignees
            if assignees:
                assignee_str = ",".join(assignees)
                cmd = ["gh", "issue", "edit", issue_number, "--add-assignee", assignee_str]
            else:
                # Remove all assignees (not directly supported, would need API call)
                return True, None  # Skip for now

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return True, None
            else:
                return False, stderr.decode().strip()
        except Exception as e:
            return False, str(e)

    @staticmethod
    async def _update_labels(issue_number: str, labels: List[str]) -> Tuple[bool, Optional[str]]:
        """Update GitHub issue labels"""
        try:
            if labels:
                label_str = ",".join(labels)
                cmd = ["gh", "issue", "edit", issue_number, "--add-label", label_str]
            else:
                return True, None  # Skip empty labels

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return True, None
            else:
                return False, stderr.decode().strip()
        except Exception as e:
            return False, str(e)

    @staticmethod
    async def check_github_health() -> Dict[str, Any]:
        """Check GitHub integration health and configuration"""
        health_status = {
            "github_integration_enabled": config.is_github_integration_enabled(),
            "github_cli_available": False,
            "authenticated": False,
            "repository_configured": False,
            "api_accessible": False,
            "error_messages": [],
        }

        # If GitHub integration is disabled, return early with appropriate status
        if not config.is_github_integration_enabled():
            health_status["error_messages"].append("GitHub integration is disabled via configuration")
            health_status["info"] = "To enable: set GITHUB_INTEGRATION_ENABLED=true and configure GITHUB_TOKEN and GITHUB_REPO"
            return health_status

        try:
            # Check GitHub CLI availability
            result = subprocess.run(["gh", "--version"], capture_output=True, text=True, timeout=5)
            health_status["github_cli_available"] = result.returncode == 0

            if not health_status["github_cli_available"]:
                health_status["error_messages"].append("GitHub CLI not installed or not in PATH")
                return health_status

            # Check authentication
            result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=10)
            health_status["authenticated"] = result.returncode == 0

            if not health_status["authenticated"]:
                health_status["error_messages"].append("GitHub CLI not authenticated. Run 'gh auth login'")
                return health_status

            # Check repository configuration
            health_status["repository_configured"] = GitHubUtils.is_github_available()

            if not health_status["repository_configured"]:
                health_status["error_messages"].append("Not in a GitHub repository or no GitHub remote configured")
                return health_status

            # Test API access with a simple call
            try:
                result = subprocess.run(
                    ["gh", "repo", "view", "--json", "name"], capture_output=True, text=True, timeout=10
                )
                health_status["api_accessible"] = result.returncode == 0

                if not health_status["api_accessible"]:
                    health_status["error_messages"].append("Cannot access GitHub API - check network and permissions")

            except Exception as e:
                health_status["api_accessible"] = False
                health_status["error_messages"].append(f"API test failed: {e}")

        except Exception as e:
            health_status["error_messages"].append(f"Health check failed: {e}")

        return health_status

    @staticmethod
    async def fetch_all_repository_issues(
        state: str = "all",
        limit: Optional[int] = None,
        search_query: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch all repository issues with pagination support
        
        Args:
            state: Issue state filter ('open', 'closed', 'all'). Default: 'all'
            limit: Maximum number of issues to fetch. Default: 1000
            search_query: GitHub search query to filter issues
            
        Returns:
            List of issues with metadata, or None if GitHub unavailable
        """
        if not GitHubUtils.is_github_available():
            return None

        try:
            cmd = [
                "gh", "issue", "list",
                "--json", "number,title,body,state,assignees,labels,updatedAt,url,createdAt",
                "--state", state
            ]

            # Set limit (default to 1000 for comprehensive fetch)
            if limit:
                cmd.extend(["--limit", str(limit)])
            else:
                cmd.extend(["--limit", "1000"])

            # Add search query if provided
            if search_query:
                cmd.extend(["--search", search_query])

            # Execute GitHub CLI command
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                issues = json.loads(stdout.decode())
                
                # Add sync metadata to each issue
                current_time = datetime.now(timezone.utc).isoformat()
                for issue in issues:
                    issue["sync_timestamp"] = current_time
                    issue["etag"] = GitHubUtils._generate_etag(issue)
                    
                    # Ensure consistent format for assignees
                    if issue.get("assignees"):
                        issue["assignees"] = [
                            {"login": assignee.get("login", "")} 
                            for assignee in issue["assignees"]
                        ]
                    else:
                        issue["assignees"] = []
                
                return issues
            else:
                error_msg = stderr.decode().strip()
                print(f"Error fetching GitHub issues: {error_msg}")
                return None

        except subprocess.TimeoutExpired:
            print("Timeout while fetching GitHub issues")
            return None
        except json.JSONDecodeError as e:
            print(f"Error parsing GitHub API response: {e}")
            return None
        except Exception as e:
            print(f"Error fetching GitHub issues: {e}")
            return None

    @staticmethod
    async def fetch_repository_issues_paginated(
        per_page: int = 100,
        max_pages: Optional[int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch repository issues with explicit pagination for large repositories
        
        Args:
            per_page: Issues per page (max 100 for GitHub CLI)
            max_pages: Maximum pages to fetch (None for all)
            
        Returns:
            List of all issues across pages, or None if GitHub unavailable
        """
        if not GitHubUtils.is_github_available():
            return None

        all_issues = []
        page = 1
        
        try:
            while True:
                # Fetch current page
                search_query = f"is:issue"
                if per_page > 100:
                    per_page = 100  # GitHub CLI limit
                    
                issues = await GitHubUtils.fetch_all_repository_issues(
                    limit=per_page,
                    search_query=f"{search_query} created:>{datetime.now().year - 10}-01-01"
                )
                
                if not issues or len(issues) == 0:
                    break
                    
                all_issues.extend(issues)
                
                # Check if we should continue
                if max_pages and page >= max_pages:
                    break
                if len(issues) < per_page:
                    break  # Last page
                    
                page += 1
                
                # Small delay to respect rate limits
                await asyncio.sleep(0.1)
                
            return all_issues
            
        except Exception as e:
            print(f"Error in paginated fetch: {e}")
            return all_issues if all_issues else None

    @staticmethod
    async def validate_github_project_access(
        project_id: Optional[str] = None,
        project_type: str = "v2"
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validate access to GitHub project and return project details
        
        Args:
            project_id: GitHub project ID (if None, uses config)
            project_type: Project type 'v1' or 'v2' (if None, uses config)
            
        Returns:
            Tuple of (success, error_message, project_data)
        """
        if not GitHubUtils.is_github_available():
            return False, "GitHub integration is not available", None

        # Use config values if not provided
        if project_id is None:
            project_id = config.get_github_project_id()
        if project_type is None:
            project_type = config.get_github_project_type()

        if not project_id:
            return False, "No GitHub project ID configured", None

        try:
            # Use GitHub CLI to validate project access
            if project_type == "v2":
                # For v2 projects, use the new project commands
                cmd = ["gh", "project", "view", project_id, "--format", "json"]
            else:
                # For v1 projects (classic), project ID is numeric
                cmd = ["gh", "api", f"/projects/{project_id}"]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                try:
                    project_data = json.loads(stdout.decode())
                    return True, None, project_data
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON response from GitHub API: {e}", None
            else:
                error_msg = stderr.decode().strip()
                if "Not Found" in error_msg or "404" in error_msg:
                    return False, f"Project {project_id} not found or no access", None
                elif "Forbidden" in error_msg or "403" in error_msg:
                    return False, f"No permission to access project {project_id}", None
                else:
                    return False, f"GitHub API error: {error_msg}", None

        except subprocess.TimeoutExpired:
            return False, "Timeout while validating GitHub project access", None
        except Exception as e:
            return False, f"Error validating GitHub project access: {e}", None

    @staticmethod
    async def list_github_projects(owner: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """
        List available GitHub projects for an owner
        
        Args:
            owner: GitHub owner (user or org). If None, uses current authenticated user
            
        Returns:
            List of project data or None if error
        """
        if not GitHubUtils.is_github_available():
            return None

        try:
            cmd = ["gh", "project", "list", "--format", "json"]
            
            if owner:
                cmd.extend(["--owner", owner])

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                try:
                    projects = json.loads(stdout.decode())
                    return projects
                except json.JSONDecodeError as e:
                    print(f"Error parsing project list: {e}")
                    return None
            else:
                error_msg = stderr.decode().strip()
                print(f"Error listing GitHub projects: {error_msg}")
                return None

        except Exception as e:
            print(f"Error listing GitHub projects: {e}")
            return None

    @staticmethod
    async def get_project_fields(project_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get fields for a GitHub project
        
        Args:
            project_id: GitHub project ID
            
        Returns:
            List of project fields or None if error
        """
        if not GitHubUtils.is_github_available():
            return None

        try:
            cmd = ["gh", "project", "field-list", project_id, "--format", "json"]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                try:
                    fields = json.loads(stdout.decode())
                    return fields
                except json.JSONDecodeError as e:
                    print(f"Error parsing project fields: {e}")
                    return None
            else:
                error_msg = stderr.decode().strip()
                print(f"Error getting project fields: {error_msg}")
                return None

        except Exception as e:
            print(f"Error getting project fields: {e}")
            return None

    @staticmethod
    async def add_issue_to_project(
        issue_url: str,
        project_id: Optional[str] = None,
        initial_status: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Add a GitHub issue to a project board
        
        Args:
            issue_url: URL of the GitHub issue to add
            project_id: Project ID (if None, uses config)
            initial_status: Initial status to set (if None, uses default)
            
        Returns:
            Tuple of (success, error_message, item_data)
        """
        if not GitHubUtils.is_github_available():
            return False, "GitHub integration is not available", None

        # Use config values if not provided
        if project_id is None:
            project_id = config.get_github_project_id()

        if not project_id:
            return False, "No GitHub project ID configured", None

        try:
            # Add item to project
            cmd = ["gh", "project", "item-add", project_id, "--url", issue_url, "--format", "json"]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                try:
                    item_data = json.loads(stdout.decode())
                    
                    # Set initial status if specified and if this is a v2 project
                    if initial_status and config.get_github_project_type() == "v2":
                        item_id = item_data.get("id")
                        if item_id:
                            await GitHubUtils.update_project_item_status(
                                project_id, item_id, initial_status
                            )
                    
                    return True, None, item_data
                    
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON response: {e}", None
            else:
                error_msg = stderr.decode().strip()
                if "already exists" in error_msg.lower():
                    return True, "Issue already in project", None
                elif "Not Found" in error_msg or "404" in error_msg:
                    return False, f"Project {project_id} or issue not found", None
                elif "Forbidden" in error_msg or "403" in error_msg:
                    return False, f"No permission to modify project {project_id}", None
                else:
                    return False, f"GitHub API error: {error_msg}", None

        except subprocess.TimeoutExpired:
            return False, "Timeout while adding issue to project", None
        except Exception as e:
            return False, f"Error adding issue to project: {e}", None

    @staticmethod
    async def update_project_item_status(
        project_id: str,
        item_id: str, 
        status: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Update the status of an item in a GitHub project (v2 only)
        
        Args:
            project_id: GitHub project ID
            item_id: Project item ID
            status: New status value
            
        Returns:
            Tuple of (success, error_message)
        """
        if not GitHubUtils.is_github_available():
            return False, "GitHub integration is not available"

        try:
            # For v2 projects, we need to find the status field ID first
            fields = await GitHubUtils.get_project_fields(project_id)
            if not fields:
                return False, "Could not get project fields"

            # Find the status field
            status_field = None
            for field in fields:
                if field.get("name", "").lower() in ["status", "state"]:
                    status_field = field
                    break

            if not status_field:
                return False, "No status field found in project"

            field_id = status_field.get("id")
            if not field_id:
                return False, "Status field has no ID"

            # Update the item status using gh CLI
            cmd = [
                "gh", "project", "item-edit",
                "--project-id", project_id,
                "--id", item_id,
                "--field-id", field_id,
                "--text", status
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return True, None
            else:
                error_msg = stderr.decode().strip()
                return False, f"Failed to update status: {error_msg}"

        except Exception as e:
            return False, f"Error updating project item status: {e}"

    @staticmethod
    async def get_issue_node_id(issue_number: str) -> Optional[str]:
        """
        Get the GraphQL node ID for a GitHub issue
        
        Args:
            issue_number: GitHub issue number
            
        Returns:
            Node ID string or None if error
        """
        if not GitHubUtils.is_github_available():
            return None

        try:
            repo_parts = config.get_github_repo().split('/')
            if len(repo_parts) != 2:
                return None
            
            owner, repo_name = repo_parts
            
            query = f'query {{ repository(owner: "{owner}", name: "{repo_name}") {{ issue(number: {issue_number}) {{ id }} }} }}'
            cmd = [
                "gh", "api", "graphql", "-f", 
                f"query={query}"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                try:
                    response = json.loads(stdout.decode())
                    return response.get("data", {}).get("repository", {}).get("issue", {}).get("id")
                except json.JSONDecodeError:
                    return None
            else:
                print(f"Error getting issue node ID: {stderr.decode()}")
                return None

        except Exception as e:
            print(f"Error getting issue node ID: {e}")
            return None

    @staticmethod
    async def create_sub_issue_relationship(
        parent_issue_number: str, 
        child_issue_number: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Create a parent-child relationship between GitHub issues using GraphQL
        
        Args:
            parent_issue_number: Parent issue number
            child_issue_number: Child issue number
            
        Returns:
            Tuple of (success, error_message)
        """
        if not GitHubUtils.is_github_available():
            return False, "GitHub integration is not available"

        try:
            # Get node IDs for both issues
            parent_node_id = await GitHubUtils.get_issue_node_id(parent_issue_number)
            child_node_id = await GitHubUtils.get_issue_node_id(child_issue_number)

            if not parent_node_id:
                return False, f"Could not get node ID for parent issue #{parent_issue_number}"
            if not child_node_id:
                return False, f"Could not get node ID for child issue #{child_issue_number}"

            # Create GraphQL mutation to add sub-issue relationship
            mutation = f"""
            mutation {{
                addSubIssue(input: {{
                    issueId: "{parent_node_id}",
                    subIssueId: "{child_node_id}"
                }}) {{
                    clientMutationId
                }}
            }}
            """

            cmd = [
                "gh", "api", "graphql", 
                "-H", "GraphQL-Features: sub_issues",
                "-f", f"query={mutation}"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                try:
                    response = json.loads(stdout.decode())
                    if "errors" in response:
                        errors = response["errors"]
                        error_msg = "; ".join([err.get("message", "Unknown error") for err in errors])
                        return False, f"GraphQL errors: {error_msg}"
                    return True, None
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON response: {e}"
            else:
                error_msg = stderr.decode().strip()
                if "GraphQL-Features" in error_msg:
                    return False, "Sub-issue feature not available in this GitHub instance"
                return False, f"GitHub API error: {error_msg}"

        except Exception as e:
            return False, f"Error creating sub-issue relationship: {e}"

    @staticmethod
    async def remove_sub_issue_relationship(
        parent_issue_number: str, 
        child_issue_number: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Remove a parent-child relationship between GitHub issues using GraphQL
        
        Args:
            parent_issue_number: Parent issue number
            child_issue_number: Child issue number
            
        Returns:
            Tuple of (success, error_message)
        """
        if not GitHubUtils.is_github_available():
            return False, "GitHub integration is not available"

        try:
            # Get node IDs for both issues
            parent_node_id = await GitHubUtils.get_issue_node_id(parent_issue_number)
            child_node_id = await GitHubUtils.get_issue_node_id(child_issue_number)

            if not parent_node_id:
                return False, f"Could not get node ID for parent issue #{parent_issue_number}"
            if not child_node_id:
                return False, f"Could not get node ID for child issue #{child_issue_number}"

            # Create GraphQL mutation to remove sub-issue relationship
            mutation = f"""
            mutation {{
                removeSubIssue(input: {{
                    issueId: "{parent_node_id}",
                    subIssueId: "{child_node_id}"
                }}) {{
                    clientMutationId
                }}
            }}
            """

            cmd = [
                "gh", "api", "graphql", 
                "-H", "GraphQL-Features: sub_issues",
                "-f", f"query={mutation}"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                try:
                    response = json.loads(stdout.decode())
                    if "errors" in response:
                        errors = response["errors"]
                        error_msg = "; ".join([err.get("message", "Unknown error") for err in errors])
                        return False, f"GraphQL errors: {error_msg}"
                    return True, None
                except json.JSONDecodeError as e:
                    return False, f"Invalid JSON response: {e}"
            else:
                error_msg = stderr.decode().strip()
                return False, f"GitHub API error: {error_msg}"

        except Exception as e:
            return False, f"Error removing sub-issue relationship: {e}"

    @staticmethod
    async def sync_parent_child_relationships(task_data_list: List[Dict[str, Any]]) -> Tuple[int, int, List[str]]:
        """
        Sync parent-child relationships for existing tasks with GitHub issues
        
        Args:
            task_data_list: List of task data dictionaries
            
        Returns:
            Tuple of (linked_count, error_count, error_messages)
        """
        if not GitHubUtils.is_github_available():
            return 0, 0, ["GitHub integration is not available"]

        linked_count = 0
        error_count = 0
        error_messages = []

        try:
            # Group tasks by parent-child relationships
            parent_child_map = {}
            
            for task in task_data_list:
                parent_id = task.get("parent_task_id")
                if parent_id and task.get("github_issue_number"):
                    if parent_id not in parent_child_map:
                        parent_child_map[parent_id] = []
                    parent_child_map[parent_id].append(task)

            # Process each parent-child group
            for parent_id, children in parent_child_map.items():
                try:
                    # Find parent task data
                    parent_task = next((t for t in task_data_list if t.get("id") == parent_id), None)
                    
                    if not parent_task or not parent_task.get("github_issue_number"):
                        error_count += len(children)
                        error_messages.append(f"Parent task {parent_id} has no GitHub issue")
                        continue

                    parent_issue_number = str(parent_task["github_issue_number"])

                    # Link each child to the parent
                    for child in children:
                        try:
                            child_issue_number = str(child["github_issue_number"])
                            
                            success, error_msg = await GitHubUtils.create_sub_issue_relationship(
                                parent_issue_number, child_issue_number
                            )
                            
                            if success:
                                linked_count += 1
                            else:
                                error_count += 1
                                task_id = child.get("id", "unknown")
                                error_messages.append(f"Task {task_id}: {error_msg}")

                        except Exception as e:
                            error_count += 1
                            task_id = child.get("id", "unknown")
                            error_messages.append(f"Task {task_id}: {str(e)}")

                except Exception as e:
                    error_count += len(children)
                    error_messages.append(f"Parent {parent_id}: {str(e)}")

            return linked_count, error_count, error_messages

        except Exception as e:
            return 0, 1, [f"Failed to sync parent-child relationships: {str(e)}"]

    @staticmethod
    async def add_existing_issues_to_project(
        project_id: Optional[str] = None,
        limit: int = 50
    ) -> Tuple[int, int, List[str]]:
        """
        Add existing repository issues to project board (retroactive)
        
        Args:
            project_id: Project ID (if None, uses config)
            limit: Maximum number of issues to process
            
        Returns:
            Tuple of (added_count, error_count, error_messages)
        """
        if not GitHubUtils.is_github_available():
            return 0, 0, ["GitHub integration is not available"]

        if project_id is None:
            project_id = config.get_github_project_id()

        if not project_id:
            return 0, 0, ["No GitHub project ID configured"]

        added_count = 0
        error_count = 0
        error_messages = []

        try:
            # Get all repository issues
            issues = await GitHubUtils.fetch_all_repository_issues(limit=limit)
            if not issues:
                return 0, 0, ["No issues found in repository"]

            # Get status mappings for initial status assignment
            status_mappings = config.get_status_mappings()

            for issue in issues:
                try:
                    issue_url = issue.get("url", "")
                    issue_number = issue.get("number", "")
                    issue_state = issue.get("state", "open")

                    if not issue_url:
                        error_count += 1
                        error_messages.append(f"Issue #{issue_number}: No URL")
                        continue

                    # Determine initial status based on issue state
                    if issue_state == "closed":
                        initial_status = status_mappings.get("Complete", "Done")
                    else:
                        initial_status = status_mappings.get("Not Started", "Todo")

                    # Add to project
                    success, error, item_data = await GitHubUtils.add_issue_to_project(
                        issue_url, project_id, initial_status
                    )

                    if success:
                        added_count += 1
                    else:
                        if "already in project" not in (error or "").lower():
                            error_count += 1
                            error_messages.append(f"Issue #{issue_number}: {error}")

                    # Small delay to respect rate limits
                    await asyncio.sleep(0.1)

                except Exception as e:
                    error_count += 1
                    error_messages.append(f"Issue #{issue.get('number', 'unknown')}: {str(e)}")

            return added_count, error_count, error_messages

        except Exception as e:
            return 0, 1, [f"Failed to add existing issues: {str(e)}"]

    @staticmethod
    async def get_project_items(
        project_id: Optional[str] = None,
        limit: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get all items in a GitHub project with their current status
        
        Args:
            project_id: GitHub project ID (if None, uses config)
            limit: Maximum number of items to fetch
            
        Returns:
            List of project items with metadata, or None if error
        """
        if not GitHubUtils.is_github_available():
            return None

        if project_id is None:
            project_id = config.get_github_project_id()

        if not project_id:
            return None

        try:
            # For v2 projects, use GraphQL to get project items with status
            repo_parts = config.get_github_repo().split('/')
            if len(repo_parts) != 2:
                return None
            
            owner, repo_name = repo_parts
            
            # GraphQL query to get project items with their status
            query = f'''
            query {{
                node(id: "{project_id}") {{
                    ... on ProjectV2 {{
                        items(first: {limit}) {{
                            nodes {{
                                id
                                content {{
                                    ... on Issue {{
                                        number
                                        title
                                        url
                                        state
                                        repository {{
                                            owner {{
                                                login
                                            }}
                                            name
                                        }}
                                    }}
                                }}
                                fieldValues(first: 20) {{
                                    nodes {{
                                        ... on ProjectV2ItemFieldSingleSelectValue {{
                                            name
                                            field {{
                                                ... on ProjectV2SingleSelectField {{
                                                    name
                                                }}
                                            }}
                                        }}
                                        ... on ProjectV2ItemFieldTextValue {{
                                            text
                                            field {{
                                                ... on ProjectV2Field {{
                                                    name
                                                }}
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
            }}
            '''

            cmd = [
                "gh", "api", "graphql", 
                "-f", f"query={query}"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                try:
                    response = json.loads(stdout.decode())
                    
                    if "errors" in response:
                        print(f"GraphQL errors: {response['errors']}")
                        return None
                    
                    project_data = response.get("data", {}).get("node", {})
                    items = project_data.get("items", {}).get("nodes", [])
                    
                    # Process items and extract status information
                    processed_items = []
                    
                    for item in items:
                        content = item.get("content", {})
                        
                        # Only process Issue items (not other content types)
                        if content.get("number"):
                            # Find status field value
                            status = "Unknown"
                            field_values = item.get("fieldValues", {}).get("nodes", [])
                            
                            for field_value in field_values:
                                field_name = field_value.get("field", {}).get("name", "").lower()
                                if field_name in ["status", "state"]:
                                    if "name" in field_value:  # Single select field
                                        status = field_value["name"]
                                    elif "text" in field_value:  # Text field
                                        status = field_value["text"]
                                    break
                            
                            # Check if this issue belongs to our repository
                            issue_repo = content.get("repository", {})
                            issue_owner = issue_repo.get("owner", {}).get("login", "")
                            issue_repo_name = issue_repo.get("name", "")
                            
                            if issue_owner == owner and issue_repo_name == repo_name:
                                processed_items.append({
                                    "project_item_id": item.get("id"),
                                    "issue_number": content.get("number"),
                                    "issue_title": content.get("title"),
                                    "issue_url": content.get("url"),
                                    "issue_state": content.get("state"),
                                    "project_status": status,
                                    "repository": f"{issue_owner}/{issue_repo_name}"
                                })
                    
                    return processed_items
                    
                except json.JSONDecodeError as e:
                    print(f"Error parsing GraphQL response: {e}")
                    return None
            else:
                error_msg = stderr.decode().strip()
                print(f"Error fetching project items: {error_msg}")
                return None

        except Exception as e:
            print(f"Error getting project items: {e}")
            return None

    @staticmethod
    async def sync_from_project_board(
        tasks_with_github_issues: List[Dict[str, Any]],
        project_id: Optional[str] = None
    ) -> Tuple[int, int, List[str]]:
        """
        Sync lifecycle task statuses from GitHub project board changes
        
        Args:
            tasks_with_github_issues: List of task data with GitHub issue numbers
            project_id: GitHub project ID (if None, uses config)
            
        Returns:
            Tuple of (updated_count, error_count, error_messages)
        """
        if not GitHubUtils.is_github_available():
            return 0, 0, ["GitHub integration is not available"]

        if project_id is None:
            project_id = config.get_github_project_id()

        if not project_id:
            return 0, 0, ["No GitHub project ID configured"]

        updated_count = 0
        error_count = 0
        error_messages = []

        try:
            # Get all project items with their current status
            project_items = await GitHubUtils.get_project_items(project_id)
            if not project_items:
                return 0, 0, ["Could not fetch project items"]

            # Create mapping of issue number to project status
            issue_to_status = {}
            for item in project_items:
                issue_number = item.get("issue_number")
                project_status = item.get("project_status")
                if issue_number and project_status:
                    issue_to_status[str(issue_number)] = project_status

            # Get reverse status mappings (GitHub project status -> lifecycle status)
            reverse_mappings = config.get_reverse_status_mappings()

            # Process each task with GitHub issue
            for task in tasks_with_github_issues:
                try:
                    task_id = task.get("id")
                    current_status = task.get("status")
                    github_issue_number = str(task.get("github_issue_number", ""))
                    
                    if not github_issue_number or github_issue_number not in issue_to_status:
                        continue  # Skip tasks without GitHub issues or not in project
                    
                    project_status = issue_to_status[github_issue_number]
                    
                    # Map project status to lifecycle status
                    target_lifecycle_status = reverse_mappings.get(project_status)
                    
                    if not target_lifecycle_status:
                        error_count += 1
                        error_messages.append(
                            f"Task {task_id}: No mapping for project status '{project_status}'"
                        )
                        continue
                    
                    # Check if status change is needed
                    if current_status != target_lifecycle_status:
                        # Return the detected change - actual update will be handled by caller
                        error_messages.append({
                            "type": "status_change",
                            "task_id": task_id,
                            "current_status": current_status,
                            "target_status": target_lifecycle_status,
                            "project_status": project_status
                        })
                        updated_count += 1
                    
                except Exception as e:
                    error_count += 1
                    task_id = task.get("id", "unknown")
                    error_messages.append(f"Task {task_id}: {str(e)}")

            return updated_count, error_count, error_messages

        except Exception as e:
            return 0, 1, [f"Failed to sync from project board: {str(e)}"]
