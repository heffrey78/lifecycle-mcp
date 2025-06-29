#!/bin/bash

# Get MCP_DIR from environment variable or prompt user
if [ -z "$MCP_DIR" ]; then
    echo "MCP_DIR environment variable not set."
    read -p "Enter MCP directory path: " MCP_DIR
    if [ -z "$MCP_DIR" ]; then
        echo "Error: MCP directory path is required"
        exit 1
    fi
fi

# Expand tilde to home directory if present
MCP_DIR="${MCP_DIR/#\~/$HOME}"

# Check if MCP_DIR exists
if [ ! -d "$MCP_DIR" ]; then
    echo "Error: Directory $MCP_DIR does not exist"
    exit 1
fi

# Check if server.py exists
if [ ! -f "$MCP_DIR/lifecycle_mcp/server.py" ]; then
    echo "Error: $MCP_DIR/lifecycle_mcp/server.py not found"
    exit 1
fi

# Add the MCP server
claude mcp add lifecycle python3.10 "$MCP_DIR/lifecycle_mcp/server.py" -e LIFECYCLE_DB=./lifecycle.db