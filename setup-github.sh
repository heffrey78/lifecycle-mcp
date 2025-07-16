#!/bin/bash
# GitHub Integration Setup Script for lifecycle-mcp
# This script helps configure GitHub integration interactively

set -e

echo "🔧 Lifecycle MCP GitHub Integration Setup"
echo "========================================"
echo

# Check if user wants GitHub integration
read -p "Do you want to enable GitHub integration? (y/N): " enable_github
if [[ ! "$enable_github" =~ ^[Yy]$ ]]; then
    echo "GitHub integration will remain disabled (default)."
    echo "To run without GitHub: uv run server.py"
    exit 0
fi

echo "Enabling GitHub integration..."

# Check if gh CLI is available
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) is not installed."
    echo "Please install it from: https://cli.github.com/"
    echo "Or use manual token setup in CONFIGURATION.md"
    exit 1
fi

# Check if user is authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ GitHub CLI is not authenticated."
    echo "Please run: gh auth login"
    exit 1
fi

echo "✅ GitHub CLI is available and authenticated"

# Get current repository
if git rev-parse --git-dir > /dev/null 2>&1; then
    current_repo=$(git remote get-url origin 2>/dev/null | sed 's/.*github\.com[:/]\([^/]*\/[^/]*\)\.git.*/\1/' | sed 's/\.git$//')
    if [[ "$current_repo" == *"github.com"* ]]; then
        echo "🔍 Detected repository: $current_repo"
        read -p "Use this repository? (Y/n): " use_current
        if [[ ! "$use_current" =~ ^[Nn]$ ]]; then
            GITHUB_REPO="$current_repo"
        fi
    fi
fi

# Ask for repository if not detected or user declined
if [[ -z "$GITHUB_REPO" ]]; then
    read -p "Enter GitHub repository (owner/name): " GITHUB_REPO
    if [[ -z "$GITHUB_REPO" ]]; then
        echo "❌ Repository is required"
        exit 1
    fi
fi

# Validate repository access
echo "🔍 Validating repository access..."
if ! gh repo view "$GITHUB_REPO" &> /dev/null; then
    echo "❌ Cannot access repository: $GITHUB_REPO"
    echo "Please check:"
    echo "  - Repository exists"
    echo "  - You have access to it"
    echo "  - Repository name is in 'owner/name' format"
    exit 1
fi

echo "✅ Repository access confirmed"

# Get GitHub token
GITHUB_TOKEN=$(gh auth token)
if [[ -z "$GITHUB_TOKEN" ]]; then
    echo "❌ Could not get GitHub token"
    exit 1
fi

echo "✅ GitHub token obtained"

# Create environment setup
cat > .env << EOF
# GitHub Integration Configuration
export GITHUB_INTEGRATION_ENABLED=true
export GITHUB_REPO="$GITHUB_REPO"
export GITHUB_TOKEN="$GITHUB_TOKEN"

# Optional: Uncomment to use custom database
# export LIFECYCLE_DB="./lifecycle.db"
EOF

echo "✅ Configuration saved to .env file"

# Test configuration
echo "🧪 Testing configuration..."
if GITHUB_INTEGRATION_ENABLED=true GITHUB_REPO="$GITHUB_REPO" GITHUB_TOKEN="$GITHUB_TOKEN" uv run python3 -c "
from src.lifecycle_mcp.config import config
from src.lifecycle_mcp.github_utils import GitHubUtils
import asyncio

async def test_config():
    if not config.is_github_integration_enabled():
        print('❌ Integration not enabled')
        return False
    
    if not GitHubUtils.is_github_available():
        print('❌ GitHub not available')
        return False
    
    health = await GitHubUtils.check_github_health()
    if health['error_messages']:
        print('❌ Health check failed:', health['error_messages'])
        return False
    
    print('✅ GitHub integration is ready!')
    return True

import sys
result = asyncio.run(test_config())
sys.exit(0 if result else 1)
" 2>/dev/null; then
    echo "✅ Configuration test passed!"
else
    echo "❌ Configuration test failed"
    echo "Please check the troubleshooting guide in CONFIGURATION.md"
    exit 1
fi

echo
echo "🎉 GitHub integration setup complete!"
echo
echo "To use the configuration:"
echo "  source .env && uv run server.py"
echo
echo "Or add to your shell profile:"
echo "  echo 'source $(pwd)/.env' >> ~/.bashrc"
echo
echo "📖 For more configuration options, see CONFIGURATION.md"