# PantaChevi

**Hot Call for your chilli field.**

PantaChevi is a decision desk for chilli farmers in the Guntur region. A farmer asks
"Should I spray tomorrow?" and three specialist agents (weather, crop stage, market)
report in parallel. A supervisor reconciles any disagreement and returns one call with
the reason attached. "Panta" is Telugu for crop and "chevi" is ear.

Built for the Build, Ship, Shape: Amazon Developer Hackathon, Alexa+ track
(self-hosted MCP server over Streamable HTTP, plus a simulated Alexa+ web desk).

## Status

This is the day-1 build. Read this table before judging what works.

| Part | State |
|---|---|
| MCP server (Streamable HTTP, `/mcp`) with `ask_advice` and `get_field_status` | Working, tested with a real MCP client |
| Weather agent | Open-Meteo forecast (worst hour in the next 24h). Falls back to a clearly labelled stub if the call fails. **Live response shape not yet checked against the real API** |
| Crop stage agent | Working; last spray date comes from logged activities |
| Market agent | Uses **mandi prices typed in** by the farmer or trader (`log_price`, or the form on the web page). Says so plainly when no recent price exists. No live feed |
| Supervisor and conflict reconciliation | Working, deterministic rules |
| Simulated Alexa+ web page (typed input) | Working |
| Rules file | **Every value is a sample placeholder, not agronomic advice** |
| Live mandi price feed (data.gov.in / Agmarknet) | Not yet, needs an API key |
| PostgreSQL memory (fields, sprays, pickings) with `log_activity` and `register_field` | Working, tested against a real PostgreSQL 16. Falls back to in-memory when `DATABASE_URL` is unset |
| Redis cache | Not yet (weather cache is in-process for now) |
| Amazon Bedrock + Strands supervisor | Not yet |
| Telugu voice, spoken replies | Not yet |

Nothing in this repository should be used for real farming decisions until the rules in
`rules/chilli_guntur.json` are verified against a named source.

## Run it

Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn pantachevi.server:app --port 8000
```

- Web desk: <http://localhost:8000/>
- MCP endpoint: `http://localhost:8000/mcp`
- REST: `POST /api/advice` with `{"field_id": "demo-1", "question": "Should I spray tomorrow?"}`
- Health: `GET /api/health`
- Memory: `POST /api/fields`, `GET /api/fields/{id}`, `POST /api/fields/{id}/activities` with `{"kind": "spray"}`

- Prices: `POST /api/prices` with `{"mandi": "Guntur", "price_per_quintal": 16200}`, `GET /api/prices/{mandi}`

MCP tools: `ask_advice`, `get_field_status`, `log_activity`, `log_price`, `register_field`.

Run the tests:

```bash
python -m pytest -q
```

### Call the MCP server

```python
import asyncio
from mcp import Client

async def main():
    async with Client("http://localhost:8000/mcp") as c:
        res = await c.call_tool("ask_advice", {"field_id": "demo-1", "question": "Should I spray tomorrow?"})
        print(res.content[0].text)

asyncio.run(main())
```

### Memory (PostgreSQL)

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://pantachevi:pantachevi_local_dev@localhost:5432/pantachevi
python -m pantachevi.reset_demo   # re-dates the demo field before a demo
```

Tables are created on startup. The last spray date is derived from logged `spray`
activities, so logging a spray changes the next answer. Without `DATABASE_URL` the app
uses an in-memory store. To also run the Postgres tests, point
`PANTACHEVI_TEST_DATABASE_URL` at a throwaway database (the tests drop its tables).

Known limit: the write tools have no authentication yet, so on a public URL anyone who
knows a field id can log activity on it. Do not put a real farmer's data on a public
deployment before that is added.

### Mandi prices

Prices are typed in, in rupees per quintal. The newest entry counts only if it is at most
3 days old. The trend compares it with the entry nearest to 7 days earlier (between 4 and
10 days before). With no usable price the market report says so, has confidence 0.1, and
is left out of the "agents disagree" message. Entering the same mandi and date again
replaces the earlier entry, and a jump of 30% or more is saved with a typo warning. These
cut-offs are choices made in `pantachevi/data/prices.py`, not verified market rules. The
demo field uses its own mandi, "Guntur (demo)", so its seeded prices never mix with real
Guntur entries.

### Weather source

`PANTACHEVI_WEATHER=live` (default) calls Open-Meteo, caches for 30 minutes, and on any
failure uses placeholder data tagged `stub-fallback` with lower confidence; the reply says
so. `PANTACHEVI_WEATHER=stub` uses the fixed forecast (rain 70% at 14:00), which the tests
and the scripted demo rely on. Open-Meteo's free tier is non-commercial.

### Deploying behind a public hostname

The MCP SDK rejects requests whose `Host` header is not on an allow-list (HTTP 421).
Localhost is allowed by default. For a public deployment set:

```bash
export PANTACHEVI_ALLOWED_HOSTS="your.public.hostname"
# optional, only if a browser client on another origin calls /mcp:
export PANTACHEVI_ALLOWED_ORIGINS="https://your.public.hostname"
```

## How a decision is made

```
question -> supervisor -> weather agent    \
                          crop stage agent  } run in parallel, each returns
                          market agent     /  {agent, status, summary, evidence, confidence}
                       -> reconcile -> verdict + reason + conflict + follow-up
```

Agent thresholds come from `rules/chilli_guntur.json`. Each rule carries a `status`
(`sample` or `verified`) and a `source`. The API reports `rules_verified: false` until
every rule is verified, and the web page shows a banner while that is the case.

Demo scenario (demo field, day 98 after sowing, last sprayed 6 days ago): rain is
forecast, the pre-harvest interval blocks a spray, and the market is rising. The weather
and crop stage agents say unfavourable, the market agent says favourable, and the
verdict is "Skip the spray. Start picking in 7 days." with a re-check of the forecast in
2 days.

## Layout

```
pantachevi/
  server.py        FastAPI app, MCP server, REST endpoint
  supervisor.py    runs agents, reconciles, builds the Decision
  agents/          weather.py, crop_stage.py, market.py
  data/stubs.py    stub forecast, prices and the demo field
  rules.py         rules loader
  models.py        report and decision shapes
rules/chilli_guntur.json
web/               simulated Alexa+ desk and legal page
tests/
docker-compose.yml PostgreSQL and Redis for the next build
```

## Hackathon disclosure

Started on 13 October 2026, inside the submission period. No pre-existing project code is
used. Third-party libraries: the MCP Python SDK, FastAPI, Uvicorn, Pydantic, HTTPX and
pytest. Code was written with an AI coding assistant (Claude).

Not affiliated with, endorsed by or sponsored by Amazon.

## Licence

MIT. See `LICENSE`.
