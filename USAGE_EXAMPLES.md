# Lifecycle MCP Usage Examples

## Understanding the Setup

The lifecycle-mcp server can be used in different ways depending on your needs:

### 1. **One Server, Multiple Projects** (Recommended)

Install once, use everywhere. Each project gets its own database.

```bash
# Install lifecycle-mcp globally (do this once)
cd /Users/you/repos/lifecycle-mcp
pip install -e .

# Project A - E-commerce site
cd /Users/you/projects/ecommerce-site
claude mcp add lifecycle lifecycle-mcp -e LIFECYCLE_DB=./lifecycle.db
# Creates: /Users/you/projects/ecommerce-site/lifecycle.db

# Project B - Mobile app
cd /Users/you/projects/mobile-app
claude mcp add lifecycle lifecycle-mcp -e LIFECYCLE_DB=./lifecycle.db
# Creates: /Users/you/projects/mobile-app/lifecycle.db

# Each project has its own separate lifecycle database!
```

### 2. **Shared Database Across Projects**

Use one database for related projects:

```bash
# Create a shared database location
mkdir -p ~/lifecycle-data

# Add server with shared database
claude mcp add lifecycle lifecycle-mcp -e LIFECYCLE_DB=~/lifecycle-data/shared.db

# All projects using this configuration share the same database
```

### 3. **Project-Specific Virtual Environment**

For complete isolation:

```bash
# Create virtual environment in your project
cd /Users/you/projects/my-app
python -m venv .venv
source .venv/bin/activate

# Install lifecycle-mcp in this venv
pip install -e /path/to/lifecycle-mcp

# Add using the venv's Python
claude mcp add lifecycle .venv/bin/lifecycle-mcp -e LIFECYCLE_DB=./lifecycle.db
```

## Common Scenarios

### Scenario 1: Team Development

Your team clones the lifecycle-mcp repo to a standard location:

```bash
# Team standard location
TEAM_MCP_PATH="/opt/mcp-servers/lifecycle-mcp"

# Each developer adds it to their Claude
claude mcp add lifecycle $(which python) $TEAM_MCP_PATH/server.py -e LIFECYCLE_DB=./lifecycle.db
```

### Scenario 2: Personal Projects

Install globally for all your personal projects:

```bash
# One-time setup
pip install --user -e ~/repos/lifecycle-mcp

# Use in any project
cd ~/projects/anything
claude mcp add lifecycle lifecycle-mcp -e LIFECYCLE_DB=./lifecycle.db
```

### Scenario 3: Testing Different Versions

Run directly without installation:

```bash
# Clone specific version/branch
git clone -b feature-xyz https://github.com/heffrey78/lifecycle-mcp.git lifecycle-test
cd lifecycle-test

# Run directly with uv
claude mcp add lifecycle-test $(which uv) -- --directory $(pwd) run server.py -e LIFECYCLE_DB=./test.db
```

## Troubleshooting

### "Command not found: lifecycle-mcp"

The command isn't in your PATH. Solutions:

1. Find where it's installed:
   ```bash
   pip show -f lifecycle-mcp | grep lifecycle-mcp
   ```

2. Use the full path:
   ```bash
   claude mcp add lifecycle /full/path/to/lifecycle-mcp -e LIFECYCLE_DB=./lifecycle.db
   ```

3. Or run from source:
   ```bash
   claude mcp add lifecycle $(which python) /path/to/lifecycle-mcp/server.py -e LIFECYCLE_DB=./lifecycle.db
   ```

### Multiple Python Versions

Be specific about which Python to use:

```bash
# Use specific Python version
claude mcp add lifecycle python3.11 /path/to/lifecycle-mcp/server.py -e LIFECYCLE_DB=./lifecycle.db

# Or with pyenv
claude mcp add lifecycle $(pyenv which python) /path/to/lifecycle-mcp/server.py -e LIFECYCLE_DB=./lifecycle.db
```

### Database Location Best Practices

1. **Per-project database** (default):
   ```bash
   LIFECYCLE_DB=./lifecycle.db  # Creates in current directory
   ```

2. **Centralized databases**:
   ```bash
   LIFECYCLE_DB=~/Documents/lifecycle-dbs/project-name.db
   ```

3. **Shared team database**:
   ```bash
   LIFECYCLE_DB=/shared/team/lifecycle.db
   ```

## Configuration File Examples

### Basic Configuration

`~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "lifecycle": {
      "command": "lifecycle-mcp",
      "env": {
        "LIFECYCLE_DB": "./lifecycle.db"
      }
    }
  }
}
```

### Advanced Configuration

```json
{
  "mcpServers": {
    "lifecycle-dev": {
      "command": "/Users/me/repos/lifecycle-mcp/.venv/bin/lifecycle-mcp",
      "env": {
        "LIFECYCLE_DB": "./lifecycle-dev.db",
        "LOG_LEVEL": "DEBUG"
      }
    },
    "lifecycle-prod": {
      "command": "lifecycle-mcp",
      "env": {
        "LIFECYCLE_DB": "/Users/me/Documents/projects/production.db"
      }
    }
  }
}
```

This allows you to have multiple configurations for different purposes!