#!/usr/bin/env python3
"""
Sync Parent-Child GitHub Issue Relationships Script

This script connects to the lifecycle database, finds all tasks that have both
a parent_task_id and a github_issue_number, and uses the GitHubUtils to create
GitHub parent-child issue links where the parent also has a GitHub issue.

Usage:
    python sync_github_relationships.py [--dry-run] [--verbose]

Environment Variables:
    LIFECYCLE_DB: Path to the SQLite database (default: ./lifecycle.db)
    GITHUB_INTEGRATION_ENABLED: Set to 'true' to enable GitHub integration
    GITHUB_TOKEN: GitHub authentication token
    GITHUB_REPO: Repository in format 'owner/repo'
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add the src directory to the path to import lifecycle_mcp modules
script_dir = Path(__file__).parent
src_dir = script_dir / "src"
sys.path.insert(0, str(src_dir))

from lifecycle_mcp.config import config
from lifecycle_mcp.database_manager import DatabaseManager
from lifecycle_mcp.github_utils import GitHubUtils


class GitHubRelationshipSyncer:
    """Syncs parent-child relationships between lifecycle tasks and GitHub issues"""

    def __init__(self, db_manager: DatabaseManager, dry_run: bool = False, verbose: bool = False):
        self.db_manager = db_manager
        self.dry_run = dry_run
        self.verbose = verbose
        self.logger = self._setup_logging()

    def _setup_logging(self) -> logging.Logger:
        """Set up logging configuration"""
        logger = logging.getLogger("github_sync")
        logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        
        # Create console handler
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(handler)
        
        return logger

    def get_tasks_with_github_issues(self) -> List[Dict]:
        """Query all tasks that have GitHub issue numbers"""
        query = """
        SELECT id, task_number, subtask_number, version, title, status, priority,
               parent_task_id, github_issue_number, github_issue_url, assignee,
               created_at, updated_at
        FROM tasks 
        WHERE github_issue_number IS NOT NULL 
          AND github_issue_number != ''
        ORDER BY task_number, subtask_number, version
        """
        
        self.logger.debug("Querying tasks with GitHub issues...")
        
        with self.db_manager.get_connection(row_factory=True) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
        
        # Convert sqlite3.Row objects to dictionaries
        tasks = []
        for row in rows:
            task_dict = dict(row)
            tasks.append(task_dict)
        
        self.logger.info(f"Found {len(tasks)} tasks with GitHub issue numbers")
        return tasks

    def find_parent_child_relationships(self, tasks: List[Dict]) -> List[Tuple[Dict, Dict]]:
        """Find parent-child task pairs where both have GitHub issues"""
        relationships = []
        task_by_id = {task['id']: task for task in tasks}
        
        for task in tasks:
            parent_id = task.get('parent_task_id')
            if parent_id and parent_id in task_by_id:
                parent_task = task_by_id[parent_id]
                if parent_task.get('github_issue_number'):
                    relationships.append((parent_task, task))
        
        self.logger.info(f"Found {len(relationships)} parent-child relationships to sync")
        
        if self.verbose:
            for parent, child in relationships:
                self.logger.debug(
                    f"  Parent: {parent['id']} (Issue #{parent['github_issue_number']}) -> "
                    f"Child: {child['id']} (Issue #{child['github_issue_number']})"
                )
        
        return relationships

    async def check_github_health(self) -> Tuple[bool, List[str]]:
        """Check if GitHub integration is properly configured"""
        self.logger.info("Checking GitHub integration health...")
        
        health = await GitHubUtils.check_github_health()
        
        is_healthy = (
            health.get('github_integration_enabled', False) and
            health.get('github_cli_available', False) and
            health.get('authenticated', False) and
            health.get('repository_configured', False) and
            health.get('api_accessible', False)
        )
        
        error_messages = health.get('error_messages', [])
        
        if is_healthy:
            self.logger.info("GitHub integration is healthy and ready")
        else:
            self.logger.error("GitHub integration is not properly configured:")
            for error in error_messages:
                self.logger.error(f"  - {error}")
            
            if 'info' in health:
                self.logger.info(f"Info: {health['info']}")
        
        return is_healthy, error_messages

    async def sync_relationships(self, relationships: List[Tuple[Dict, Dict]]) -> Dict[str, int]:
        """Sync parent-child relationships to GitHub"""
        stats = {
            'total': len(relationships),
            'successful': 0,
            'failed': 0,
            'skipped': 0
        }
        
        if not relationships:
            self.logger.info("No relationships to sync")
            return stats
        
        self.logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}Starting sync of {len(relationships)} relationships...")
        
        # Prepare task data for the GitHubUtils sync method
        all_tasks = []
        for parent, child in relationships:
            all_tasks.extend([parent, child])
        
        # Remove duplicates while preserving order
        unique_tasks = []
        seen_ids = set()
        for task in all_tasks:
            if task['id'] not in seen_ids:
                unique_tasks.append(task)
                seen_ids.add(task['id'])
        
        if self.dry_run:
            self.logger.info("[DRY RUN] Would sync the following relationships:")
            for parent, child in relationships:
                self.logger.info(
                    f"  {parent['id']} (#{parent['github_issue_number']}) -> "
                    f"{child['id']} (#{child['github_issue_number']})"
                )
            stats['skipped'] = len(relationships)
            return stats
        
        # Use the existing GitHubUtils method to sync relationships
        linked_count, error_count, error_messages = await GitHubUtils.sync_parent_child_relationships(unique_tasks)
        
        stats['successful'] = linked_count
        stats['failed'] = error_count
        
        self.logger.info(f"Sync completed: {linked_count} successful, {error_count} failed")
        
        if error_messages:
            self.logger.error("Errors encountered during sync:")
            for error in error_messages:
                self.logger.error(f"  - {error}")
        
        return stats

    async def run_sync(self) -> Dict[str, any]:
        """Main sync operation"""
        result = {
            'started_at': datetime.now().isoformat(),
            'github_healthy': False,
            'tasks_found': 0,
            'relationships_found': 0,
            'sync_stats': {},
            'errors': [],
            'completed_at': None
        }
        
        try:
            # Check GitHub health
            is_healthy, health_errors = await self.check_github_health()
            result['github_healthy'] = is_healthy
            
            if not is_healthy:
                result['errors'].extend(health_errors)
                if not GitHubUtils.is_github_available():
                    self.logger.warning("GitHub integration is disabled or unavailable")
                    result['sync_stats'] = {'total': 0, 'successful': 0, 'failed': 0, 'skipped': 0}
                    return result
            
            # Get tasks with GitHub issues
            tasks = self.get_tasks_with_github_issues()
            result['tasks_found'] = len(tasks)
            
            # Find parent-child relationships
            relationships = self.find_parent_child_relationships(tasks)
            result['relationships_found'] = len(relationships)
            
            # Sync relationships
            sync_stats = await self.sync_relationships(relationships)
            result['sync_stats'] = sync_stats
            
        except Exception as e:
            error_msg = f"Sync operation failed: {str(e)}"
            self.logger.error(error_msg)
            result['errors'].append(error_msg)
        
        finally:
            result['completed_at'] = datetime.now().isoformat()
        
        return result


def setup_environment():
    """Set up environment variables for GitHub integration"""
    # Check if GitHub integration is explicitly disabled
    if os.environ.get('GITHUB_INTEGRATION_ENABLED', '').lower() == 'false':
        print("GitHub integration is explicitly disabled via GITHUB_INTEGRATION_ENABLED=false")
        return
    
    # If not set, try to enable with sensible defaults
    if not os.environ.get('GITHUB_INTEGRATION_ENABLED'):
        print("GitHub integration not explicitly configured. Attempting to enable...")
        os.environ['GITHUB_INTEGRATION_ENABLED'] = 'true'
    
    # Try to get GitHub token from various sources
    if not os.environ.get('GITHUB_TOKEN'):
        # Try to get token from gh CLI
        try:
            import subprocess
            result = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                token = result.stdout.strip()
                os.environ['GITHUB_TOKEN'] = token
                print("Using GitHub token from gh CLI")
            else:
                print("Could not get GitHub token from gh CLI")
        except Exception:
            print("Could not execute gh CLI to get token")
    
    # Try to get repository from git remote
    if not os.environ.get('GITHUB_REPO'):
        try:
            import subprocess
            result = subprocess.run(['git', 'remote', 'get-url', 'origin'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                remote_url = result.stdout.strip()
                # Parse GitHub repo from URL
                if 'github.com' in remote_url:
                    # Handle both SSH and HTTPS URLs
                    if remote_url.startswith('git@'):
                        # SSH: git@github.com:owner/repo.git
                        repo_part = remote_url.split(':')[-1]
                    else:
                        # HTTPS: https://github.com/owner/repo.git
                        repo_part = '/'.join(remote_url.split('/')[-2:])
                    
                    # Remove .git suffix if present
                    if repo_part.endswith('.git'):
                        repo_part = repo_part[:-4]
                    
                    os.environ['GITHUB_REPO'] = repo_part
                    print(f"Using GitHub repository: {repo_part}")
                else:
                    print("Remote origin is not a GitHub repository")
            else:
                print("Could not get git remote origin")
        except Exception as e:
            print(f"Could not get git remote: {e}")


def print_summary(result: Dict):
    """Print a summary of the sync operation"""
    print("\n" + "="*60)
    print("GITHUB RELATIONSHIP SYNC SUMMARY")
    print("="*60)
    
    print(f"Started: {result['started_at']}")
    print(f"Completed: {result['completed_at']}")
    print(f"GitHub Integration Healthy: {'✅' if result['github_healthy'] else '❌'}")
    print(f"Tasks with GitHub Issues Found: {result['tasks_found']}")
    print(f"Parent-Child Relationships Found: {result['relationships_found']}")
    
    sync_stats = result.get('sync_stats', {})
    print(f"\nSync Results:")
    print(f"  Total Relationships: {sync_stats.get('total', 0)}")
    print(f"  Successfully Linked: {sync_stats.get('successful', 0)}")
    print(f"  Failed: {sync_stats.get('failed', 0)}")
    print(f"  Skipped (dry run): {sync_stats.get('skipped', 0)}")
    
    if result.get('errors'):
        print(f"\nErrors ({len(result['errors'])}):")
        for error in result['errors']:
            print(f"  ❌ {error}")
    
    if sync_stats.get('successful', 0) > 0:
        print(f"\n✅ Successfully linked {sync_stats['successful']} parent-child relationships!")
    elif sync_stats.get('failed', 0) > 0:
        print(f"\n❌ {sync_stats['failed']} relationships failed to link")
    elif result['relationships_found'] == 0:
        print(f"\nℹ️  No parent-child relationships found to sync")
    
    print("="*60)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Sync parent-child GitHub issue relationships for existing tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true', 
        help='Show what would be synced without making changes'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true', 
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--db-path',
        default=None,
        help='Path to lifecycle database (default: from LIFECYCLE_DB env var or ./lifecycle.db)'
    )
    
    args = parser.parse_args()
    
    # Set up environment
    setup_environment()
    
    # Initialize database manager
    db_path = args.db_path or os.environ.get('LIFECYCLE_DB', './lifecycle.db')
    if not Path(db_path).exists():
        print(f"Database not found at {db_path}")
        print("Please ensure the lifecycle database exists or set LIFECYCLE_DB environment variable")
        return 1
    
    db_manager = DatabaseManager(db_path=db_path)
    
    # Initialize syncer
    syncer = GitHubRelationshipSyncer(
        db_manager=db_manager,
        dry_run=args.dry_run,
        verbose=args.verbose
    )
    
    # Run sync
    result = await syncer.run_sync()
    
    # Print summary
    print_summary(result)
    
    # Return appropriate exit code
    if result.get('errors'):
        return 1
    elif result.get('sync_stats', {}).get('failed', 0) > 0:
        return 2
    else:
        return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))