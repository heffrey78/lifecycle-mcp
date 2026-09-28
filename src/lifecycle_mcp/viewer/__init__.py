"""A read-only view of a tracker, generated as one self-contained file (REQ-0006-INTF-00).

Nothing here is part of the MCP server. The viewer is a reader of a database, not a mode of the server: it opens the
file read-only, takes a snapshot and renders it, so looking at a tracker costs no session, no connection and no
permission. The command that drives it lives in scripts/, because stdout belongs to the protocol anywhere under src/.
"""
