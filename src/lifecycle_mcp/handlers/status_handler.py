#!/usr/bin/env python3
"""
Status Handler for MCP Lifecycle Management Server
Handles project status and metrics operations
"""

import os
import sqlite3
from typing import Any, Dict, List

from mcp.types import TextContent

from .base_handler import BaseHandler


class StatusHandler(BaseHandler):
    """Handler for project status and metrics MCP tools"""

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return status tool definitions"""
        return [
            {
                "name": "get_project_status",
                "description": "Get overall project health metrics",
                "inputSchema": {"type": "object", "properties": {"include_blocked": {"type": "boolean"}}},
            }
        ]

    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "get_project_status":
                return self._get_project_status(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    def _get_project_status(self, **params) -> List[TextContent]:
        """Get overall project health metrics"""
        try:
            # Get requirement stats
            req_stats = self.db.execute_query(
                """
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
            """,
                fetch_all=True,
                row_factory=True,
            )

            # Get task stats
            task_stats = self.db.execute_query(
                """
                SELECT status, COUNT(*) as count
                FROM tasks
                WHERE status != 'Abandoned'
                GROUP BY status
            """,
                fetch_all=True,
                row_factory=True,
            )

            # Get blocked items
            blocked = []
            if params.get("include_blocked", True):
                try:
                    blocked = self.db.execute_query("SELECT * FROM blocked_items", fetch_all=True, row_factory=True)
                except sqlite3.OperationalError:
                    # View might not work if no dependencies exist yet
                    blocked = []

            # Get project name from current working directory
            project_name = os.path.basename(os.getcwd())

            # Build report
            report = f"""# Project Status Dashboard - {project_name}

## Requirements Overview
"""
            total_reqs = sum(r["count"] for r in req_stats) if req_stats else 0
            if total_reqs > 0:
                for stat in req_stats:
                    percentage = stat["count"] / total_reqs * 100
                    report += f"- **{stat['status']}**: {stat['count']} ({percentage:.1f}%)"
                    if stat["avg_completion"]:
                        report += f" - Avg {stat['avg_completion']:.1f}% complete"
                    report += "\n"
            else:
                report += "- No requirements found\n"

            report += "\n## Tasks Overview\n"
            total_tasks = sum(t["count"] for t in task_stats) if task_stats else 0
            if total_tasks > 0:
                for stat in task_stats:
                    percentage = stat["count"] / total_tasks * 100
                    report += f"- **{stat['status']}**: {stat['count']} ({percentage:.1f}%)\n"
            else:
                report += "- No tasks found\n"

            if blocked:
                report += f"\n## ⚠️ Blocked Items ({len(blocked)})\n"
                for item in blocked[:10]:  # Show first 10
                    report += f"- {item['item_type'].upper()} {item['id']}: {item['title']}\n"
                    report += f"  Blocked by: {item['blocking_items']}\n"

            # Add summary metrics
            report += self._add_summary_metrics(req_stats, task_stats)

            # Create above-the-fold response for project status
            total_reqs = sum(r["count"] for r in req_stats) if req_stats else 0
            total_tasks = sum(t["count"] for t in task_stats) if task_stats else 0
            completed_tasks = next((t["count"] for t in task_stats if t["status"] == "Complete"), 0)

            key_info = f"Project {project_name} status"
            action_info = f"📈 {total_reqs} requirements | {completed_tasks}/{total_tasks} tasks complete"
            if blocked:
                action_info += f" | ⚠️ {len(blocked)} blocked"

            return self._create_above_fold_response("INFO", key_info, action_info, report)

        except Exception as e:
            return self._create_error_response("Failed to get project status", e)

    def _add_summary_metrics(self, req_stats, task_stats) -> str:
        """Add summary metrics to the status report"""
        summary = "\n## Summary Metrics\n"

        # Calculate totals
        total_reqs = sum(r["count"] for r in req_stats) if req_stats else 0
        total_tasks = sum(t["count"] for t in task_stats) if task_stats else 0

        # Calculate completion percentages
        validated_reqs = sum(r["count"] for r in req_stats if r["status"] == "Validated") if req_stats else 0
        completed_tasks = sum(t["count"] for t in task_stats if t["status"] == "Complete") if task_stats else 0

        req_completion = (validated_reqs / total_reqs * 100) if total_reqs > 0 else 0
        task_completion = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

        summary += f"- **Total Requirements**: {total_reqs}\n"
        summary += f"- **Requirements Completion**: {req_completion:.1f}% ({validated_reqs}/{total_reqs})\n"
        summary += f"- **Total Tasks**: {total_tasks}\n"
        summary += f"- **Task Completion**: {task_completion:.1f}% ({completed_tasks}/{total_tasks})\n"

        # Calculate velocity metrics if we have data
        if req_stats or task_stats:
            summary += self._calculate_velocity_metrics()

        return summary

    def _calculate_velocity_metrics(self) -> str:
        """Calculate velocity and trend metrics"""
        try:
            # Get recent activity (last 7 days)
            recent_reqs = self.db.execute_query(
                """
                SELECT COUNT(*) as count FROM requirements 
                WHERE updated_at >= datetime('now', '-7 days')
            """,
                fetch_one=True,
            )

            recent_tasks = self.db.execute_query(
                """
                SELECT COUNT(*) as count FROM tasks 
                WHERE updated_at >= datetime('now', '-7 days')
            """,
                fetch_one=True,
            )

            # Get completed items in last 7 days
            completed_reqs = self.db.execute_query(
                """
                SELECT COUNT(*) as count FROM requirements 
                WHERE status = 'Validated' AND updated_at >= datetime('now', '-7 days')
            """,
                fetch_one=True,
            )

            completed_tasks = self.db.execute_query(
                """
                SELECT COUNT(*) as count FROM tasks 
                WHERE status = 'Complete' AND updated_at >= datetime('now', '-7 days')
            """,
                fetch_one=True,
            )

            velocity = "\n### Recent Activity (Last 7 Days)\n"
            velocity += f"- **Requirements Updated**: {recent_reqs[0] if recent_reqs else 0}\n"
            velocity += f"- **Requirements Completed**: {completed_reqs[0] if completed_reqs else 0}\n"
            velocity += f"- **Tasks Updated**: {recent_tasks[0] if recent_tasks else 0}\n"
            velocity += f"- **Tasks Completed**: {completed_tasks[0] if completed_tasks else 0}\n"

            return velocity

        except Exception as e:
            self.logger.warning(f"Failed to calculate velocity metrics: {str(e)}")
            return ""

    def get_detailed_metrics(self) -> Dict[str, Any]:
        """Get detailed metrics for programmatic use"""
        try:
            metrics = {"requirements": {}, "tasks": {}, "architecture": {}, "summary": {}}

            # Requirements metrics
            req_stats = self.db.execute_query(
                """
                SELECT status, COUNT(*) as count, priority,
                       AVG(CASE WHEN task_count = 0 THEN 0 
                               ELSE CAST(tasks_completed AS FLOAT) / task_count * 100 END) as avg_completion
                FROM requirements
                WHERE status != 'Deprecated'
                GROUP BY status, priority
            """,
                fetch_all=True,
                row_factory=True,
            )

            for stat in req_stats:
                status = stat["status"]
                if status not in metrics["requirements"]:
                    metrics["requirements"][status] = {}
                metrics["requirements"][status][stat["priority"]] = {
                    "count": stat["count"],
                    "avg_completion": stat["avg_completion"] or 0,
                }

            # Task metrics
            task_stats = self.db.execute_query(
                """
                SELECT status, priority, COUNT(*) as count
                FROM tasks
                WHERE status != 'Abandoned'
                GROUP BY status, priority
            """,
                fetch_all=True,
                row_factory=True,
            )

            for stat in task_stats:
                status = stat["status"]
                if status not in metrics["tasks"]:
                    metrics["tasks"][status] = {}
                metrics["tasks"][status][stat["priority"]] = stat["count"]

            # Architecture metrics
            arch_stats = self.db.execute_query(
                """
                SELECT status, type, COUNT(*) as count
                FROM architecture
                GROUP BY status, type
            """,
                fetch_all=True,
                row_factory=True,
            )

            for stat in arch_stats:
                status = stat["status"]
                if status not in metrics["architecture"]:
                    metrics["architecture"][status] = {}
                metrics["architecture"][status][stat["type"]] = stat["count"]

            # Summary metrics
            total_reqs = sum(
                sum(
                    priorities.values() if isinstance(priorities, dict) else [priorities]
                    for priorities in status_data.values()
                )
                for status_data in metrics["requirements"].values()
            )

            total_tasks = sum(
                sum(
                    priorities.values() if isinstance(priorities, dict) else [priorities]
                    for priorities in status_data.values()
                )
                for status_data in metrics["tasks"].values()
            )

            metrics["summary"] = {
                "total_requirements": total_reqs,
                "total_tasks": total_tasks,
                "completion_percentage": {
                    "requirements": (
                        sum(metrics["requirements"].get("Validated", {}).values()) / total_reqs * 100
                        if total_reqs > 0
                        else 0
                    ),
                    "tasks": (
                        sum(metrics["tasks"].get("Complete", {}).values()) / total_tasks * 100 if total_tasks > 0 else 0
                    ),
                },
            }

            return metrics

        except Exception as e:
            self.logger.error(f"Failed to get detailed metrics: {str(e)}")
            return {}
