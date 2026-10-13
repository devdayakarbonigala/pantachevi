import os

import pytest

# Tests must never depend on the network, a database or today's real weather.
os.environ.setdefault("PANTACHEVI_WEATHER", "stub")
os.environ.pop("DATABASE_URL", None)

from pantachevi import store as store_mod  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_store():
    """Every test gets its own in-memory store seeded with the demo field."""
    store_mod.set_store(store_mod.MemoryStore())
    yield
    store_mod.set_store(None)


@pytest.fixture(scope="session")
def client():
    """One app instance for the whole run: the MCP session manager can only be
    started once per process, so the lifespan must not be re-entered per module."""
    from fastapi.testclient import TestClient

    from pantachevi.server import app

    with TestClient(app) as c:
        yield c
