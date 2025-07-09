#!/usr/bin/env python3
"""
GitHub integration utilities for MCP Lifecycle Management Server
Provides GitHub CLI integration for issue management
"""

import asyncio
import json
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


class GitHubUtils:
    """Utilities for GitHub CLI integration"""

    @staticmethod
    def is_github_available() -> bool:
        """Check if gh CLI is available and we're in a git repo with remote"""
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
                return stdout.decode().strip()
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
                issue_data["sync_timestamp"] = datetime.now().isoformat()
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
                    if updates["state"] == "closed" and current_issue["state"] == "open":
                        success, error_msg = await GitHubUtils._close_issue(issue_number, updates.get("comment"))
                    elif updates["state"] == "open" and current_issue["state"] == "closed":
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
                    last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                    github_updated_dt = datetime.fromisoformat(github_updated.replace("Z", "+00:00"))

                    if github_updated_dt <= last_sync_dt:
                        return True, "Already in sync", github_issue
                except ValueError:
                    pass  # Continue with sync if date parsing fails

            # Detect conflicts
            conflicts = []

            # Check state conflicts
            task_status = task_data.get("status", "")
            github_state = github_issue.get("state", "")

            task_is_complete = task_status == "Complete"
            github_is_closed = github_state == "closed"

            if task_is_complete != github_is_closed:
                conflicts.append(f"Status mismatch: Task={task_status}, GitHub={github_state}")

            # Check assignee conflicts
            task_assignee = task_data.get("assignee", "")
            github_assignees = [a.get("login", "") for a in github_issue.get("assignees", [])]
            github_assignee = github_assignees[0] if github_assignees else ""

            if task_assignee != github_assignee:
                conflicts.append(f"Assignee mismatch: Task={task_assignee}, GitHub={github_assignee}")

            if conflicts:
                conflict_msg = "Sync conflicts detected:\n" + "\n".join(f"- {c}" for c in conflicts)
                return False, conflict_msg, github_issue

            return True, "In sync", github_issue

        except Exception as e:
            return False, f"Error syncing with GitHub: {e}", None

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
            "github_cli_available": False,
            "authenticated": False,
            "repository_configured": False,
            "api_accessible": False,
            "error_messages": [],
        }

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
