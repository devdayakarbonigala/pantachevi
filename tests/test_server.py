import asyncio



def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "rules_verified": False}


def test_pages(client):
    assert client.get("/").status_code == 200
    assert "PantaChevi" in client.get("/").text
    assert client.get("/legal").status_code == 200


def test_advice_endpoint(client):
    r = client.post("/api/advice", json={"field_id": "demo-1", "question": "Should I spray tomorrow?"})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"]["conflict"] is True
    assert body["rules_verified"] is False
    assert len(body["reports"]) == 3


def test_advice_unknown_field(client):
    r = client.post("/api/advice", json={"field_id": "nope", "question": "spray?"})
    assert r.status_code == 404


def test_advice_validates_input(client):
    assert client.post("/api/advice", json={"question": "x"}).status_code == 422


def test_unknown_path_is_404(client):
    assert client.get("/nothing-here").status_code == 404


def test_mcp_endpoint_answers_without_redirect(client):
    r = client.post(
        "/mcp",
        headers={"accept": "application/json, text/event-stream", "content-type": "application/json"},
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "pytest", "version": "0"}},
        },
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text


def test_mcp_tool_in_memory():
    from mcp import Client

    from pantachevi.server import mcp

    async def run():
        async with Client(mcp) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            res = await c.call_tool("ask_advice", {"field_id": "demo-1", "question": "Should I spray tomorrow?"})
            return names, res

    names, res = asyncio.run(run())
    assert names == {"ask_advice", "get_field_status", "log_activity", "register_field"}
    assert "Skip the spray" in res.content[0].text
