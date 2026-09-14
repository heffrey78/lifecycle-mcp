"""The server's stdout is the MCP protocol channel and must carry only JSON-RPC.

Migrations used to print progress there: 19 junk lines on a fresh database and more on every
restart. scripts/mcp_handshake_smoke.py drives a real server process through a handshake twice
(fresh database, then restart) and fails on any stdout line that isn't a JSON-RPC message. CI runs
the same script against a freshly installed server.
"""

import subprocess
import sys
from pathlib import Path

SMOKE_SCRIPT = Path(__file__).parent.parent / "scripts" / "mcp_handshake_smoke.py"
SERVER_COMMAND = [sys.executable, "-c", "from lifecycle_mcp.server import main; main()"]


def test_stdout_carries_only_jsonrpc_on_fresh_start_and_restart(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT), *SERVER_COMMAND], capture_output=True, text=True, cwd=tmp_path, timeout=180
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("clean stdout") == 2
