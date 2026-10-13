"""Shared data shapes. The agent report format is a contract between the
agents, the supervisor and the web page: change it in one place only."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["favourable", "unfavourable", "caution"]


class Field_(BaseModel):
    """One chilli plot. Named Field_ to avoid clashing with pydantic.Field."""

    id: str
    farmer: str
    crop: str = "chilli"
    variety: str
    village: str
    lat: float
    lng: float
    sowing_date: date
    last_spray_date: date | None = None
    mandi: str


class AgentReport(BaseModel):
    agent: str
    status: Status
    summary: str
    evidence: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    # True when any rule used to reach this report is still a sample value.
    uses_sample_rules: bool = True


class Verdict(BaseModel):
    action: str
    reason: str
    conflict: bool
    conflict_detail: str | None = None
    follow_up: str | None = None


class Decision(BaseModel):
    field_id: str
    question: str
    intent: str
    reports: list[AgentReport]
    verdict: Verdict
    rules_verified: bool
    disclaimer: str
