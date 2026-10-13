"""FastAPI app. One decision function, three doors:

  POST /api/advice   used by the simulated Alexa+ web page
  /mcp               self-hosted MCP server (Streamable HTTP), the Alexa+ path
  GET  /             the web page itself
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from .data import stubs
from .rules import load_rules
from .supervisor import decide

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

mcp = MCPServer("PantaChevi")


def _get_field(field_id: str):
    field = stubs.demo_fields().get(field_id)
    if field is None:
        raise KeyError(field_id)
    return field


@mcp.tool()
async def ask_advice(field_id: str, question: str) -> dict:
    """Give one clear call (spray, wait or pick) for a chilli field.

    Checks the weather forecast, the crop stage and the mandi price in parallel,
    reconciles any disagreement, and returns a verdict with the reason and each
    agent's report. Use field_id "demo-1" for the demo field.
    """
    try:
        field = _get_field(field_id)
    except KeyError:
        return {"error": f"Unknown field_id '{field_id}'. Known fields: {sorted(stubs.demo_fields())}"}
    return (await decide(field, question)).model_dump(mode="json")


@mcp.tool()
async def get_field_status(field_id: str) -> dict:
    """Return the stored details of a field and whether its rules are verified."""
    try:
        field = _get_field(field_id)
    except KeyError:
        return {"error": f"Unknown field_id '{field_id}'."}
    return {
        "field": field.model_dump(mode="json"),
        "rules_note": load_rules()["status_note"],
    }


# The MCP ASGI app is mounted below; its session manager must be started by us
# because Starlette does not run the lifespan of a mounted sub-app.
def _csv_env(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


# The MCP SDK checks the Host header (DNS-rebinding protection) and rejects any
# host that is not listed with 421. Localhost is allowed by default. On a public
# deployment set PANTACHEVI_ALLOWED_HOSTS to the public hostname, for example
# "pantachevi.example.com" (include a port or ":*" if clients send one).
_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver"] + _csv_env("PANTACHEVI_ALLOWED_HOSTS")
_origins = ["http://127.0.0.1:*", "http://localhost:*"] + _csv_env("PANTACHEVI_ALLOWED_ORIGINS")

# Served at exactly /mcp (no redirect): many MCP clients do not re-send a POST
# after a 307, so a mount at /mcp that redirects to /mcp/ would break them.
mcp_asgi = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_hosts,
        allowed_origins=_origins,
    ),
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="PantaChevi", lifespan=lifespan)


class AdviceRequest(BaseModel):
    field_id: str = "demo-1"
    question: str = Field(min_length=2, max_length=500)


@app.get("/api/health")
async def health():
    return {"status": "ok", "rules_verified": all(
        r["status"] == "verified" for g in load_rules()["rules"].values() for r in g.values()
    )}


@app.post("/api/advice")
async def advice(req: AdviceRequest):
    try:
        field = _get_field(req.field_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown field_id '{req.field_id}'")
    return (await decide(field, req.question)).model_dump(mode="json")


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/legal")
async def legal():
    return FileResponse(WEB_DIR / "legal.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# Must stay last: a root mount is a catch-all, so every route above wins first
# and only /mcp (and unknown paths, which it 404s) reach the MCP app.
app.mount("/", mcp_asgi)
