#!/bin/bash
#
# Sync GitHub Parent-Child Issue Relationships
# Wrapper script to run the Python sync script with proper environment setup
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/sync_github_relationships.py"

# Function to show usage
show_usage() {
    echo "Usage: $0 [--dry-run] [--verbose] [--help]"
    echo ""
    echo "Sync parent-child GitHub issue relationships for existing tasks."
    echo ""
    echo "Options:"
    echo "  --dry-run     Show what would be synced without making changes"
    echo "  --verbose     Enable verbose logging"
    echo "  --help        Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  LIFECYCLE_DB  Path to the SQLite database (default: ./lifecycle.db)"
    echo "  GITHUB_TOKEN  GitHub authentication token (auto-detected from gh CLI)"
    echo "  GITHUB_REPO   Repository in format 'owner/repo' (auto-detected from git remote)"
    echo ""
    echo "Prerequisites:"
    echo "  - GitHub CLI (gh) must be installed and authenticated"
    echo "  - Must be run from a GitHub repository directory"
    echo "  - Lifecycle database must exist"
}

# Parse arguments
DRY_RUN=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Check prerequisites
echo "Checking prerequisites..."

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed or not in PATH"
    echo "Please install it from: https://cli.github.com/"
    exit 1
fi

# Check if gh is authenticated
if ! gh auth status &> /dev/null; then
    echo "Error: GitHub CLI is not authenticated"
    echo "Please run: gh auth login"
    exit 1
fi

# Check if we're in a git repository
if ! git rev-parse --git-dir &> /dev/null; then
    echo "Error: Not in a git repository"
    echo "Please run this script from within a git repository"
    exit 1
fi

# Check if lifecycle database exists
DB_PATH="${LIFECYCLE_DB:-./lifecycle.db}"
if [[ ! -f "$DB_PATH" ]]; then
    echo "Error: Lifecycle database not found at $DB_PATH"
    echo "Please ensure the database exists or set LIFECYCLE_DB environment variable"
    exit 1
fi

# Set up environment variables
export GITHUB_INTEGRATION_ENABLED=true

# Get GitHub token from gh CLI if not already set
if [[ -z "$GITHUB_TOKEN" ]]; then
    echo "Getting GitHub token from gh CLI..."
    export GITHUB_TOKEN=$(gh auth token)
fi

# Get GitHub repository from git remote if not already set
if [[ -z "$GITHUB_REPO" ]]; then
    echo "Getting GitHub repository from git remote..."
    REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
    if [[ "$REMOTE_URL" == *"github.com"* ]]; then
        if [[ "$REMOTE_URL" == git@* ]]; then
            # SSH: git@github.com:owner/repo.git
            REPO_PART=$(echo "$REMOTE_URL" | cut -d: -f2)
        else
            # HTTPS: https://github.com/owner/repo.git
            REPO_PART=$(echo "$REMOTE_URL" | sed 's|.*/\([^/]*/[^/]*\)$|\1|')
        fi
        # Remove .git suffix if present
        export GITHUB_REPO=$(echo "$REPO_PART" | sed 's/\.git$//')
    else
        echo "Error: Remote origin is not a GitHub repository"
        exit 1
    fi
fi

echo "Configuration:"
echo "  Database: $DB_PATH"
echo "  Repository: $GITHUB_REPO"
echo "  Dry Run: $DRY_RUN"
echo "  Verbose: $VERBOSE"
echo ""

# Build command arguments
ARGS=()
if [[ "$DRY_RUN" == true ]]; then
    ARGS+=("--dry-run")
fi
if [[ "$VERBOSE" == true ]]; then
    ARGS+=("--verbose")
fi

# Run the Python script
echo "Running sync script..."
python "$PYTHON_SCRIPT" "${ARGS[@]}"