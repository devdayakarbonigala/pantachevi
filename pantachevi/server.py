"""FastAPI app. One decision function, three doors:

  POST /api/advice   used by the simulated Alexa+ web page
  /mcp               self-hosted MCP server (Streamable HTTP), the Alexa+ path
  GET  /             the web page itself
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from . import service
from .rules import load_rules
from .store import get_store
from .supervisor import decide

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

mcp = MCPServer("PantaChevi")


async def _run(fn, *args, **kwargs):
    """Store calls are blocking (psycopg), so keep them off the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


@mcp.tool()
async def ask_advice(field_id: str, question: str) -> dict:
    """Give one clear call (spray, wait or pick) for a chilli field.

    Checks the weather forecast, the crop stage and the mandi price in parallel,
    reconciles any disagreement, and returns a verdict with the reason and each
    agent's report. The last spray date comes from logged activities. Use
    field_id "demo-1" for the demo field.
    """
    store = await _run(get_store)
    field = await _run(store.get_field, field_id)
    if field is None:
        return {"error": f"Unknown field_id '{field_id}'. Known fields: {await _run(store.list_field_ids)}"}
    return (await decide(field, question)).model_dump(mode="json")


@mcp.tool()
async def get_field_status(field_id: str) -> dict:
    """Return a field's stored details, days since sowing, days since the last
    spray and its recent activities, plus whether the rules are verified."""
    store = await _run(get_store)
    state = await _run(service.field_state, store, field_id)
    if "error" not in state:
        state["rules_note"] = load_rules()["status_note"]
    return state


@mcp.tool()
async def log_activity(
    field_id: str,
    kind: str,
    on_date: date | None = None,
    product: str | None = None,
    notes: str | None = None,
) -> dict:
    """Record something the farmer did on a field: kind is "spray", "pick" or "note".

    on_date defaults to today and cannot be in the future. A logged spray resets
    the days-since-last-spray count that the crop stage agent uses, so only log
    sprays that really happened.
    """
    store = await _run(get_store)
    return await _run(service.log_activity, store, field_id, kind, on_date, product, notes)


@mcp.tool()
async def log_price(
    mandi: str,
    price_per_quintal: int,
    on_date: date | None = None,
    note: str | None = None,
) -> dict:
    """Record today's mandi price for dried red chilli, in rupees per quintal
    (for example mandi "Guntur", price 16200). The market agent compares it with
    the entry from about a week earlier. Entering the same mandi and date again
    replaces the earlier entry."""
    store = await _run(get_store)
    return await _run(service.log_price, store, mandi, price_per_quintal, on_date, note)


@mcp.tool()
async def register_field(
    field_id: str,
    farmer: str,
    variety: str,
    village: str,
    lat: float,
    lng: float,
    sowing_date: date,
    mandi: str = "Guntur",
) -> dict:
    """Register a new chilli field. field_id is a short lowercase slug such as
    "ramu-plot-1". Fails if the id is already taken."""
    store = await _run(get_store)
    return await _run(service.register_field, store, field_id, farmer, variety, village,
                      lat, lng, sowing_date, mandi)


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
    await _run(get_store)  # connect to Postgres now, so a bad DATABASE_URL fails at startup
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


class ActivityRequest(BaseModel):
    kind: str
    on_date: date | None = None
    product: str | None = None
    notes: str | None = None


class PriceRequest(BaseModel):
    mandi: str = Field(min_length=1, max_length=60)
    price_per_quintal: int
    on_date: date | None = None
    note: str | None = Field(default=None, max_length=200)


class FieldRequest(BaseModel):
    field_id: str
    farmer: str = Field(min_length=1, max_length=80)
    variety: str = Field(min_length=1, max_length=60)
    village: str = Field(min_length=1, max_length=80)
    lat: float
    lng: float
    sowing_date: date
    mandi: str = Field(default="Guntur", min_length=1, max_length=60)


def _or_http_error(result: dict, status: int = 400) -> dict:
    if "error" in result:
        raise HTTPException(status_code=404 if result["error"].startswith("Unknown field_id") else status,
                            detail=result["error"])
    return result


@app.post("/api/advice")
async def advice(req: AdviceRequest):
    store = await _run(get_store)
    field = await _run(store.get_field, req.field_id)
    if field is None:
        raise HTTPException(status_code=404, detail=f"Unknown field_id '{req.field_id}'")
    return (await decide(field, req.question)).model_dump(mode="json")


@app.get("/api/fields/{field_id}")
async def field_status(field_id: str):
    store = await _run(get_store)
    return _or_http_error(await _run(service.field_state, store, field_id))


@app.post("/api/fields", status_code=201)
async def create_field(req: FieldRequest):
    store = await _run(get_store)
    return _or_http_error(await _run(service.register_field, store, **req.model_dump()))


@app.post("/api/fields/{field_id}/activities", status_code=201)
async def add_activity(field_id: str, req: ActivityRequest):
    store = await _run(get_store)
    return _or_http_error(await _run(service.log_activity, store, field_id, req.kind,
                                     req.on_date, req.product, req.notes))


@app.post("/api/prices", status_code=201)
async def add_price(req: PriceRequest):
    store = await _run(get_store)
    return _or_http_error(await _run(service.log_price, store, req.mandi, req.price_per_quintal,
                                     req.on_date, req.note))


@app.get("/api/prices/{mandi}")
async def get_mandi_prices(mandi: str):
    from .data.prices import get_prices

    store = await _run(get_store)
    return {
        "market_view": await _run(get_prices, store, mandi),
        "recent_prices": [p.model_dump(mode="json") for p in await _run(store.list_prices, mandi, 7)],
    }


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
