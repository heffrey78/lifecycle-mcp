# GitHub Parent-Child Relationship Sync Script

## Overview

This script (`sync_github_relationships.py`) connects to the lifecycle database to find existing tasks that have both parent-child relationships and GitHub issues, then creates the corresponding parent-child issue links in GitHub using the GitHub GraphQL API.

## Files Created

1. **`sync_github_relationships.py`** - Main Python script with comprehensive functionality
2. **`sync-github-relationships.sh`** - Bash wrapper script for easy execution
3. **Updated `README.md`** - Added documentation in the GitHub Integration section

## Features

### Core Functionality
- Connects to lifecycle SQLite database using existing `DatabaseManager`
- Queries all tasks with GitHub issue numbers
- Identifies parent-child relationships where both parent and child have GitHub issues
- Uses existing `GitHubUtils.sync_parent_child_relationships()` method
- Provides detailed reporting and error handling

### Safety Features
- **Dry run mode**: Preview changes without making them (`--dry-run`)
- **Environment auto-detection**: Automatically configures GitHub settings from `gh` CLI
- **Health checks**: Validates GitHub integration before proceeding
- **Graceful error handling**: Handles GitHub integration being disabled
- **Comprehensive logging**: Detailed progress and error reporting

### User Experience
- **Bash wrapper script**: Simple execution with automatic setup
- **Verbose logging**: Optional detailed output (`--verbose`)
- **Help system**: Built-in usage instructions (`--help`)
- **Status reporting**: Clear summary of operations performed

## Usage Examples

### Quick Start
```bash
# Simple execution with auto-configuration
./sync-github-relationships.sh

# Preview what would be done
./sync-github-relationships.sh --dry-run

# Detailed logging
./sync-github-relationships.sh --verbose
```

### Direct Python Script
```bash
# Manual environment setup
GITHUB_INTEGRATION_ENABLED=true \
GITHUB_TOKEN=$(gh auth token) \
GITHUB_REPO=owner/repo \
python sync_github_relationships.py
```

## Output Example

From our test run:
```
============================================================
GITHUB RELATIONSHIP SYNC SUMMARY
============================================================
Started: 2025-07-15T19:27:05.077266
Completed: 2025-07-15T19:27:11.681478
GitHub Integration Healthy: ✅
Tasks with GitHub Issues Found: 33
Parent-Child Relationships Found: 4

Sync Results:
  Total Relationships: 4
  Successfully Linked: 4
  Failed: 0
  Skipped (dry run): 0

✅ Successfully linked 4 parent-child relationships!
```

## Technical Details

### Database Query
Finds tasks with:
- Non-null `github_issue_number`
- Non-null `parent_task_id`
- Parent task also has a `github_issue_number`

### GitHub Integration
- Uses existing `GitHubUtils` class for all GitHub operations
- Leverages `sync_parent_child_relationships()` method
- Handles GitHub GraphQL API sub-issue feature
- Respects rate limits and includes retry logic

### Error Handling
- GitHub integration disabled: Graceful message and exit
- Missing prerequisites: Clear error messages with solutions
- GitHub API errors: Detailed error reporting with task IDs
- Database issues: Connection pooling and retry logic

## Prerequisites

1. **GitHub CLI**: Must be installed and authenticated (`gh auth login`)
2. **GitHub Repository**: Must be run from a GitHub repository directory
3. **Lifecycle Database**: Must exist at specified path
4. **GitHub Integration**: Automatically enabled by wrapper script

## Architecture Integration

The script integrates seamlessly with the existing lifecycle-mcp architecture:

- Uses `DatabaseManager` for all database operations
- Leverages `GitHubUtils` for all GitHub API interactions
- Follows existing async patterns and error handling
- Respects configuration system for GitHub settings
- Maintains compatibility with existing MCP server functionality

## Testing

The script was tested with:
- 33 tasks with GitHub issues in the database
- 4 parent-child relationships identified
- All 4 relationships successfully synced to GitHub
- Dry run mode working correctly
- Error handling for disabled GitHub integration
- Help system and documentation

## Future Enhancements

Potential improvements for future versions:
1. **Batch operations**: Process multiple repositories
2. **Selective sync**: Sync specific task families or date ranges
3. **Relationship removal**: Ability to remove existing GitHub sub-issue links
4. **Integration tests**: Automated testing with mock GitHub API
5. **Configuration file**: Support for persistent configuration