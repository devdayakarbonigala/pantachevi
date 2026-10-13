"""Runs the same store behaviour against a real PostgreSQL. Skipped unless
PANTACHEVI_TEST_DATABASE_URL points at a throwaway database, for example:

  PANTACHEVI_TEST_DATABASE_URL=postgresql://pantachevi:pantachevi_local_dev@localhost:5432/pantachevi_test
"""

import os
from datetime import date, timedelta

import pytest

from pantachevi import service

DSN = os.environ.get("PANTACHEVI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="PANTACHEVI_TEST_DATABASE_URL not set")

TODAY = date(2026, 10, 13)


@pytest.fixture()
def pg():
    import psycopg

    from pantachevi.store import PostgresStore

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS activities, fields CASCADE")
    return PostgresStore(DSN)


def test_demo_seeded_and_survives_a_new_connection(pg):
    from pantachevi.store import PostgresStore

    assert pg.get_field("demo-1").last_spray_date == date.today() - timedelta(days=6)
    assert PostgresStore(DSN).list_field_ids() == ["demo-1"]  # re-open: not re-seeded or duplicated


def test_memory_across_sessions(pg):
    from pantachevi.store import PostgresStore

    service.register_field(pg, "ramu-1", "Ramu", "Teja", "Nallapadu", 16.33, 80.43,
                           TODAY - timedelta(days=50), today=TODAY)
    service.log_activity(pg, "ramu-1", "spray", TODAY - timedelta(days=9), product="mancozeb", today=TODAY)
    reopened = PostgresStore(DSN)  # a fresh process would see the same thing
    assert reopened.get_field("ramu-1").last_spray_date == TODAY - timedelta(days=9)
    acts = reopened.list_activities("ramu-1")
    assert acts[0].product == "mancozeb" and acts[0].id is not None and acts[0].created_at is not None


def test_database_rejects_a_bad_kind(pg):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute("INSERT INTO activities (field_id, kind, on_date) VALUES ('demo-1','dance',now())")


def test_reset_demo_redates_it(pg):
    service.log_activity(pg, "demo-1", "spray", date.today(), today=date.today())
    pg.reset_demo()
    assert pg.get_field("demo-1").last_spray_date == date.today() - timedelta(days=6)
    assert len(pg.list_activities("demo-1")) == 1
