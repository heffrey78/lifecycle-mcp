# Lifecycle MCP Server

A Model Context Protocol (MCP) server for software lifecycle management.

## Features

- Create and manage software requirements
- Track implementation tasks
- Record architecture decisions (ADRs)
- Project status dashboards
- Requirement tracing through implementation

## Installation

```bash
pip install lifecycle-mcp
```

## Usage with Claude Code

```bash
claude mcp add lifecycle-mcp
```

## Manual Configuration

Add to your MCP configuration:

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