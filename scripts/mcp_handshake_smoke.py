#!/usr/bin/env python3
"""Prove an installed lifecycle-mcp server works: MCP handshake, tools/list, and clean stdout.

Runs two sessions against one temporary database (fresh start, then restart). Fails if the server
exits early, returns too few tools, or writes anything to stdout that isn't a JSON-RPC message
(stdout is the protocol channel). Standard library only, so CI can run it straight after a clean
`uv tool install .`.

    python3 scripts/mcp_handshake_smoke.py                      # runs `lifecycle-mcp` from PATH
    python3 scripts/mcp_handshake_smoke.py /path/to/lifecycle-mcp
    python3 scripts/mcp_handshake_smoke.py python -c "from lifecycle_mcp.server import main; main()"
"""

import json
import os
import subprocess
import sys
import tempfile
import threading

MIN_TOOLS = 20
TIMEOUT_S = 60


class SmokeFailure(Exception):
    pass


def run_session(command: list[str], env: dict[str, str], cwd: str) -> int:
    """One server session; returns the number of tools listed."""
    proc = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, env=env
    )
    watchdog = threading.Timer(TIMEOUT_S, proc.kill)
    watchdog.start()
    seen: list[str] = []

    def send(message: dict) -> None:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def await_response(request_id: int) -> dict:
        while True:
            line = proc.stdout.readline()
            if not line:
                raise SmokeFailure(f"server exited before answering request {request_id}:\n{proc.stderr.read()}")
            seen.append(line)
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                raise SmokeFailure(f"non-JSON line on stdout: {line!r}") from None
            if message.get("id") == request_id:
                if "error" in message:
                    raise SmokeFailure(f"request {request_id} failed: {message['error']}")
                return message

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            }
        )
        await_response(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = await_response(2)["result"]["tools"]
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        seen.extend(proc.stdout.read().splitlines(keepends=True))
        stderr = proc.stderr.read()
        proc.wait(timeout=TIMEOUT_S)
        watchdog.cancel()

    for line in seen:
        if line.strip() and json.loads(line).get("jsonrpc") != "2.0":
            raise SmokeFailure(f"non-JSON-RPC message on stdout: {line!r}")
    if "Traceback" in stderr:
        raise SmokeFailure(f"server logged an exception:\n{stderr}")
    if len(tools) < MIN_TOOLS:
        raise SmokeFailure(f"tools/list returned {len(tools)} tools, expected at least {MIN_TOOLS}")
    return len(tools)


def main(argv: list[str]) -> int:
    command = argv[1:] or ["lifecycle-mcp"]
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if k != "LIFECYCLE_GITHUB"}
        env["LIFECYCLE_DB"] = os.path.join(tmp, "smoke.db")
        for label in ("fresh database", "restart"):
            try:
                count = run_session(command, env, tmp)
            except SmokeFailure as failure:
                sys.stderr.write(f"FAIL ({label}): {failure}\n")
                return 1
            sys.stderr.write(f"ok ({label}): handshake complete, {count} tools, clean stdout\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
