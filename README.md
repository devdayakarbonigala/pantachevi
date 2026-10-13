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
| Crop stage and market agents | Working, but market is fed by **stub prices** |
| Supervisor and conflict reconciliation | Working, deterministic rules |
| Simulated Alexa+ web page (typed input) | Working |
| Rules file | **Every value is a sample placeholder, not agronomic advice** |
| Mandi prices | Not yet |
| PostgreSQL memory, Redis cache | Not yet (compose file is ready) |
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
