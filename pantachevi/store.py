"""Storage for fields and farm activities (sprays, pickings, notes).

Two backends behind one interface:
  PostgresStore  used when DATABASE_URL is set
  MemoryStore    used otherwise (tests, quick local runs); data is lost on restart

The last spray date is never stored on the field. It is derived from the newest
'spray' activity, so logging a spray is the only way to change it.
"""

from __future__ import annotations

import os
import threading
from datetime import date, datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .data import stubs
from .models import Field_

ActivityKind = Literal["spray", "pick", "note"]
DEMO_SEED_NOTE = "demo seed"


class Activity(BaseModel):
    id: int | None = None
    field_id: str
    kind: ActivityKind
    on_date: date
    product: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)
    created_at: datetime | None = None


class Store(Protocol):
    def get_field(self, field_id: str) -> Field_ | None: ...
    def list_field_ids(self) -> list[str]: ...
    def upsert_field(self, field: Field_) -> None: ...
    def add_activity(self, activity: Activity) -> Activity: ...
    def list_activities(self, field_id: str, limit: int = 10) -> list[Activity]: ...
    def reset_demo(self, today: date | None = None) -> None: ...


def _with_last_spray(field: Field_, sprays: list[date]) -> Field_:
    return field.model_copy(update={"last_spray_date": max(sprays) if sprays else None})


def _demo_seed(today: date | None) -> tuple[Field_, Activity]:
    demo = stubs.demo_fields(today)[stubs.DEMO_FIELD_ID]
    spray = Activity(
        field_id=demo.id,
        kind="spray",
        on_date=demo.last_spray_date,
        product="demo fungicide",
        notes=DEMO_SEED_NOTE,
    )
    return demo.model_copy(update={"last_spray_date": None}), spray


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fields: dict[str, Field_] = {}
        self._acts: list[Activity] = []
        self.reset_demo()

    def get_field(self, field_id: str) -> Field_ | None:
        with self._lock:
            f = self._fields.get(field_id)
            if f is None:
                return None
            sprays = [a.on_date for a in self._acts if a.field_id == field_id and a.kind == "spray"]
            return _with_last_spray(f, sprays)

    def list_field_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._fields)

    def upsert_field(self, field: Field_) -> None:
        with self._lock:
            self._fields[field.id] = field.model_copy(update={"last_spray_date": None})

    def add_activity(self, activity: Activity) -> Activity:
        with self._lock:
            saved = activity.model_copy(
                update={"id": len(self._acts) + 1, "created_at": datetime.now(timezone.utc)}
            )
            self._acts.append(saved)
            return saved

    def list_activities(self, field_id: str, limit: int = 10) -> list[Activity]:
        with self._lock:
            rows = [a for a in self._acts if a.field_id == field_id]
        rows.sort(key=lambda a: (a.on_date, a.id or 0), reverse=True)
        return rows[:limit]

    def reset_demo(self, today: date | None = None) -> None:
        demo, spray = _demo_seed(today)
        with self._lock:
            self._fields[demo.id] = demo
            self._acts = [a for a in self._acts if a.field_id != demo.id]
        self.add_activity(spray)


SCHEMA = """
CREATE TABLE IF NOT EXISTS fields (
    id           text PRIMARY KEY,
    farmer       text NOT NULL,
    crop         text NOT NULL DEFAULT 'chilli',
    variety      text NOT NULL,
    village      text NOT NULL,
    lat          double precision NOT NULL,
    lng          double precision NOT NULL,
    sowing_date  date NOT NULL,
    mandi        text NOT NULL
);
CREATE TABLE IF NOT EXISTS activities (
    id          bigserial PRIMARY KEY,
    field_id    text NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('spray', 'pick', 'note')),
    on_date     date NOT NULL,
    product     text,
    notes       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS activities_field_date ON activities (field_id, on_date DESC);
"""

_FIELD_COLS = "id, farmer, crop, variety, village, lat, lng, sowing_date, mandi"


class PostgresStore:
    """Synchronous psycopg store. Callers run it in a worker thread."""

    def __init__(self, dsn: str) -> None:
        import psycopg  # imported here so the memory backend needs no driver

        self._psycopg = psycopg
        self._dsn = dsn
        with self._conn() as conn:
            conn.execute(SCHEMA)
        if self.get_field(stubs.DEMO_FIELD_ID) is None:
            self.reset_demo()

    def _conn(self):
        return self._psycopg.connect(self._dsn, autocommit=True)

    def get_field(self, field_id: str) -> Field_ | None:
        with self._conn() as conn:
            row = conn.execute(f"SELECT {_FIELD_COLS} FROM fields WHERE id = %s", (field_id,)).fetchone()
            if row is None:
                return None
            last = conn.execute(
                "SELECT max(on_date) FROM activities WHERE field_id = %s AND kind = 'spray'", (field_id,)
            ).fetchone()[0]
        keys = [c.strip() for c in _FIELD_COLS.split(",")]
        return Field_(**dict(zip(keys, row)), last_spray_date=last)

    def list_field_ids(self) -> list[str]:
        with self._conn() as conn:
            return [r[0] for r in conn.execute("SELECT id FROM fields ORDER BY id").fetchall()]

    def upsert_field(self, field: Field_) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO fields (id, farmer, crop, variety, village, lat, lng, sowing_date, mandi)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET farmer=EXCLUDED.farmer, crop=EXCLUDED.crop,
                     variety=EXCLUDED.variety, village=EXCLUDED.village, lat=EXCLUDED.lat,
                     lng=EXCLUDED.lng, sowing_date=EXCLUDED.sowing_date, mandi=EXCLUDED.mandi""",
                (field.id, field.farmer, field.crop, field.variety, field.village,
                 field.lat, field.lng, field.sowing_date, field.mandi),
            )

    def add_activity(self, activity: Activity) -> Activity:
        with self._conn() as conn:
            row = conn.execute(
                """INSERT INTO activities (field_id, kind, on_date, product, notes)
                   VALUES (%s,%s,%s,%s,%s) RETURNING id, created_at""",
                (activity.field_id, activity.kind, activity.on_date, activity.product, activity.notes),
            ).fetchone()
        return activity.model_copy(update={"id": row[0], "created_at": row[1]})

    def list_activities(self, field_id: str, limit: int = 10) -> list[Activity]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, field_id, kind, on_date, product, notes, created_at FROM activities
                   WHERE field_id = %s ORDER BY on_date DESC, id DESC LIMIT %s""",
                (field_id, limit),
            ).fetchall()
        keys = ["id", "field_id", "kind", "on_date", "product", "notes", "created_at"]
        return [Activity(**dict(zip(keys, r))) for r in rows]

    def reset_demo(self, today: date | None = None) -> None:
        demo, spray = _demo_seed(today)
        self.upsert_field(demo)
        with self._conn() as conn:
            conn.execute("DELETE FROM activities WHERE field_id = %s", (demo.id,))
        self.add_activity(spray)


_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    """Process-wide store. DATABASE_URL set -> Postgres, else in-memory."""
    global _store
    with _store_lock:
        if _store is None:
            dsn = os.environ.get("DATABASE_URL", "").strip()
            _store = PostgresStore(dsn) if dsn else MemoryStore()
        return _store


def set_store(store: Store | None) -> None:
    """Swap the store (tests)."""
    global _store
    with _store_lock:
        _store = store
