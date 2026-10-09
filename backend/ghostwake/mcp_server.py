"""Expose GhostWake's read-only copilot tools over MCP, so any MCP client
(Claude Desktop, an IDE agent) can ask about alerts and vessels.

    pip install "ghostwake[mcp]"
    python -m ghostwake.mcp_server            # stdio transport

Written against the MCP Python SDK 2.x (MCPServer). On SDK 1.x the class is
`from mcp.server.fastmcp import FastMCP`; the decorators are the same.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from ghostwake.copilot import tools
from ghostwake.db import init_db, session_factory

server = MCPServer(
    name="ghostwake",
    instructions="Read-only access to GhostWake maritime alerts. Nothing here can change an alert.",
)


@server.tool(description="List alerts, highest score first. kind and status are optional filters.")
def list_alerts(kind: str | None = None, min_score: float = 0, status: str | None = None,
                limit: int = 10) -> list[dict]:
    with session_factory()() as s:
        return tools.list_alerts(s, kind=kind, min_score=min_score, status=status, limit=limit)


@server.tool(description="Full evidence, score breakdown and review history for one alert.")
def get_alert(alert_id: str) -> dict | None:
    with session_factory()() as s:
        return tools.get_alert(s, alert_id)


@server.tool(description="Static details, combined risk and alerts for a vessel, by 9-digit MMSI.")
def vessel_profile(mmsi: str) -> dict | None:
    with session_factory()() as s:
        return tools.vessel_profile(s, mmsi)


@server.tool(description="Boundaries, protected areas and monsoon fishing-ban dates in the demo area.")
def area_rules() -> dict:
    return tools.area_rules()


if __name__ == "__main__":
    init_db()
    server.run("stdio")
