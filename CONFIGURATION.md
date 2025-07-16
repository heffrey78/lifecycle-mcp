# Lifecycle MCP Configuration Guide

This document describes how to configure the Lifecycle MCP server, particularly for GitHub integration.

## Configuration Methods

The server supports configuration through:

1. **Environment Variables** (highest priority)
2. **Configuration File** (`lifecycle-config.json`)
3. **Default Values** (lowest priority)

## Core Configuration

### Database Configuration

- **LIFECYCLE_DB**: Path to SQLite database file
  - Default: `"lifecycle.db"`
  - Example: `export LIFECYCLE_DB="/path/to/my-project.db"`

### Configuration File

- **LIFECYCLE_CONFIG_FILE**: Path to JSON configuration file
  - Default: `"lifecycle-config.json"`
  - Example: `export LIFECYCLE_CONFIG_FILE="/path/to/my-config.json"`

## GitHub Integration Configuration

### Enable/Disable GitHub Integration

- **GITHUB_INTEGRATION_ENABLED**: Enable or disable GitHub integration
  - Default: `false` (disabled by default for safety)
  - Values: `true|false|1|0|yes|no|on|off`
  - Example: `export GITHUB_INTEGRATION_ENABLED=true`

### Required GitHub Settings (when enabled)

- **GITHUB_TOKEN**: GitHub Personal Access Token
  - Required when GitHub integration is enabled
  - Scopes needed: `repo`, `project` (for project board integration)
  - Example: `export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"`

- **GITHUB_REPO**: GitHub repository in owner/name format
  - Required when GitHub integration is enabled
  - Example: `export GITHUB_REPO="myorg/myproject"`

### Optional GitHub Settings

- **GITHUB_PROJECT_ID**: GitHub project board ID for automatic issue assignment
  - Optional: Only needed for project board integration
  - Example: `export GITHUB_PROJECT_ID="123456"`

- **GITHUB_PROJECT_TYPE**: GitHub project type (classic vs new projects)
  - Default: `"v2"` (new GitHub Projects)
  - Values: `"v1"` (classic projects) or `"v2"` (new projects)
  - Example: `export GITHUB_PROJECT_TYPE="v2"`

## Configuration File Format

Create a `lifecycle-config.json` file in your working directory:

```json
{
  "github_integration_enabled": true,
  "github_token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "github_repo": "myorg/myproject",
  "github_project_id": "123456",
  "github_project_type": "v2",
  "status_mappings": {
    "Not Started": "Todo",
    "In Progress": "In Progress",
    "Blocked": "Blocked",
    "Complete": "Done",
    "Abandoned": "Abandoned"
  }
}
```

## Status Mappings

Configure how lifecycle task statuses map to GitHub project board columns:

```json
{
  "status_mappings": {
    "Not Started": "Todo",
    "In Progress": "In Progress", 
    "Blocked": "Blocked",
    "Complete": "Done",
    "Abandoned": "Abandoned"
  }
}
```

## Configuration Validation

The server validates configuration on startup:

- ✅ **GitHub Disabled**: No validation needed, all GitHub operations skipped
- ✅ **GitHub Enabled**: Validates required settings (token, repo)
- ❌ **Invalid Config**: Server fails to start with clear error messages

### Example Startup Logs

**GitHub Disabled:**
```
INFO - Validating server configuration...
INFO - GitHub integration is disabled
INFO - Configuration validation completed successfully
```

**GitHub Enabled and Valid:**
```
INFO - Validating server configuration...
INFO - GitHub integration is enabled, validating configuration...
INFO - GitHub configuration validation passed
INFO - Configuration validation completed successfully
```

**GitHub Enabled but Invalid:**
```
ERROR - GitHub configuration validation failed:
  - GITHUB_TOKEN is required when GitHub integration is enabled
  - GITHUB_REPO is required when GitHub integration is enabled
```

## Security Best Practices

1. **Never commit tokens**: Add `lifecycle-config.json` to `.gitignore`
2. **Use environment variables**: Preferred for production deployments
3. **Minimal permissions**: GitHub token should have only required scopes
4. **Rotate tokens**: Regularly update GitHub tokens

## Example Configurations

### Development (GitHub Disabled)
```bash
export GITHUB_INTEGRATION_ENABLED=false
export LIFECYCLE_DB="dev-lifecycle.db"
```

### Production (GitHub Enabled)
```bash
export GITHUB_INTEGRATION_ENABLED=true
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export GITHUB_REPO="myorg/production-project"
export GITHUB_PROJECT_ID="789012"
export LIFECYCLE_DB="/data/lifecycle.db"
```

### Testing (Config File)
```json
{
  "github_integration_enabled": true,
  "github_token": "ghp_test_token_here",
  "github_repo": "myorg/test-project"
}
```

## Migration Guide for Existing Users

### Upgrading from Previous Versions

If you're upgrading from a version without configuration management:

1. **No action required for basic usage**: GitHub integration is now disabled by default
2. **To continue using GitHub integration**: Set the required environment variables
3. **Existing GitHub issues**: Will continue to work normally after enabling integration

### Migration Steps

```bash
# 1. Check if you want GitHub integration
echo "Do you want GitHub integration? (current default: disabled)"

# 2. If yes, enable it with your existing settings
export GITHUB_INTEGRATION_ENABLED=true
export GITHUB_REPO="your-org/your-repo"  # Replace with your repository

# 3. Set up authentication (choose one method):

# Method A: Use existing gh CLI authentication
export GITHUB_TOKEN=$(gh auth token)

# Method B: Use personal access token
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# 4. Restart the server
```

### Checking Migration Success

```bash
# Run this to verify your configuration
uv run python3 -c "
from src.lifecycle_mcp.config import config
from src.lifecycle_mcp.github_utils import GitHubUtils
import asyncio

async def check_config():
    print('GitHub Integration Status:')
    print(f'  Enabled: {config.is_github_integration_enabled()}')
    print(f'  Available: {GitHubUtils.is_github_available()}')
    
    health = await GitHubUtils.check_github_health()
    print(f'  CLI Available: {health[\"github_cli_available\"]}')
    print(f'  Authenticated: {health[\"authenticated\"]}')
    print(f'  Repository Configured: {health[\"repository_configured\"]}')
    print(f'  API Accessible: {health[\"api_accessible\"]}')
    
    if health['error_messages']:
        print('  Errors:', health['error_messages'])
    else:
        print('  ✅ GitHub integration is fully operational')

asyncio.run(check_config())
"
```

## Deployment Scenarios

### Scenario 1: Local Development (GitHub Disabled)

Perfect for local testing without GitHub side effects:

```bash
# .env file or shell
export GITHUB_INTEGRATION_ENABLED=false
export LIFECYCLE_DB="./dev-lifecycle.db"

# Run server
uv run server.py
```

### Scenario 2: Local Development (GitHub Enabled)

Full GitHub integration for development:

```bash
# Use your existing GitHub CLI authentication
export GITHUB_INTEGRATION_ENABLED=true
export GITHUB_REPO="your-username/your-project"
export GITHUB_TOKEN=$(gh auth token)
export LIFECYCLE_DB="./dev-lifecycle.db"

# Run server
uv run server.py
```

### Scenario 3: CI/CD Pipeline

Using a service account with limited permissions:

```bash
# In your CI environment
export GITHUB_INTEGRATION_ENABLED=true
export GITHUB_REPO="$GITHUB_REPOSITORY"  # Provided by GitHub Actions
export GITHUB_TOKEN="$GITHUB_TOKEN"      # GitHub Actions secret
export LIFECYCLE_DB="/tmp/lifecycle.db"

# Run tests or operations
uv run server.py
```

### Scenario 4: Production Server

Using a configuration file for security:

```json
// /etc/lifecycle-mcp/config.json
{
  "github_integration_enabled": true,
  "github_repo": "company/production-project",
  "github_project_id": "12345",
  "github_project_type": "v2"
}
```

```bash
# Environment setup
export GITHUB_TOKEN="$(cat /etc/lifecycle-mcp/github-token)"
export LIFECYCLE_CONFIG_FILE="/etc/lifecycle-mcp/config.json"
export LIFECYCLE_DB="/var/lib/lifecycle-mcp/lifecycle.db"

# Run with systemd or similar
uv run server.py
```

### Scenario 5: Docker Container

```dockerfile
# Dockerfile
FROM python:3.11-slim
COPY . /app
WORKDIR /app
RUN pip install uv && uv sync

# Environment variables can be set at runtime
ENV GITHUB_INTEGRATION_ENABLED=false
EXPOSE 8000
CMD ["uv", "run", "server.py"]
```

```bash
# Run with GitHub integration
docker run -e GITHUB_INTEGRATION_ENABLED=true \
           -e GITHUB_TOKEN="$GITHUB_TOKEN" \
           -e GITHUB_REPO="org/repo" \
           lifecycle-mcp
```

### Scenario 6: Multiple Projects

Using different configuration files:

```bash
# Project A
export LIFECYCLE_CONFIG_FILE="./config-project-a.json"
export LIFECYCLE_DB="./project-a.db"

# Project B  
export LIFECYCLE_CONFIG_FILE="./config-project-b.json"
export LIFECYCLE_DB="./project-b.db"
```

## Advanced Configuration

### Custom Status Mappings

```json
{
  "github_integration_enabled": true,
  "github_repo": "myorg/myproject",
  "status_mappings": {
    "Not Started": "📋 Backlog",
    "In Progress": "🚧 Development", 
    "Blocked": "🚫 Blocked",
    "Complete": "✅ Done",
    "Abandoned": "🗑️ Cancelled"
  }
}
```

### GitHub Enterprise Support

```json
{
  "github_integration_enabled": true,
  "github_repo": "myorg/myproject",
  "github_enterprise_url": "https://github.company.com",
  "github_api_url": "https://github.company.com/api/v3"
}
```

## Troubleshooting

### GitHub Integration Not Working

1. **Check configuration status**:
   ```bash
   echo "GITHUB_INTEGRATION_ENABLED: $GITHUB_INTEGRATION_ENABLED"
   echo "GITHUB_TOKEN: $([ -n "$GITHUB_TOKEN" ] && echo "present" || echo "missing")"
   echo "GITHUB_REPO: $GITHUB_REPO"
   ```

2. **Test GitHub CLI**:
   ```bash
   gh auth status
   gh repo view $GITHUB_REPO
   ```

3. **Run health check**:
   ```bash
   uv run python3 -c "
   import asyncio
   from src.lifecycle_mcp.github_utils import GitHubUtils
   health = asyncio.run(GitHubUtils.check_github_health())
   print('Health:', health)
   "
   ```

### Common Issues and Solutions

#### Issue: "GitHub integration is disabled via configuration"
**Solution**: Set `GITHUB_INTEGRATION_ENABLED=true`

#### Issue: "GITHUB_TOKEN is required"
**Solutions**:
```bash
# Option 1: Use gh CLI token
export GITHUB_TOKEN=$(gh auth token)

# Option 2: Create personal access token
# 1. Go to GitHub → Settings → Developer settings → Personal access tokens
# 2. Generate token with 'repo' scope
# 3. export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

#### Issue: "GITHUB_REPO is required"
**Solution**: Set repository in owner/name format:
```bash
export GITHUB_REPO="myusername/myproject"
```

#### Issue: "Cannot access GitHub API"
**Solutions**:
1. Check network connectivity
2. Verify token permissions (needs 'repo' scope)
3. Check if repository exists and you have access
4. Test with: `gh api repos/$GITHUB_REPO`

#### Issue: Server won't start with GitHub enabled
**Solution**: Check startup logs for validation errors:
```bash
uv run server.py 2>&1 | head -20
```

#### Issue: Tasks create without GitHub issues
**Cause**: GitHub integration disabled or misconfigured
**Solution**: Verify configuration and restart server

#### Issue: "GitHub CLI not authenticated"
**Solution**: 
```bash
gh auth login
# Follow the prompts to authenticate
```

#### Issue: Permission denied when creating issues
**Solutions**:
1. Verify token has 'repo' scope
2. Check if you have write access to the repository
3. Test with: `gh issue create --title "Test" --body "Test"`

### Server Won't Start

Check startup logs for configuration validation errors. Common startup failures:

```bash
# Error: GitHub configuration validation failed
# Solution: Fix the reported configuration issues

# Error: Database connection failed  
# Solution: Check LIFECYCLE_DB path and permissions

# Error: Import errors
# Solution: Run `uv sync` to install dependencies
```

### Performance Issues

If GitHub operations are slow:

1. **Check network latency**: `ping api.github.com`
2. **Verify rate limits**: Check GitHub API rate limit status
3. **Optimize batch operations**: Use bulk sync instead of individual syncs
4. **Consider caching**: GitHub issue data is cached with ETags

### Debug Mode

Enable debug logging for troubleshooting:

```bash
export LIFECYCLE_DEBUG=true
uv run server.py
```