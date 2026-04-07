"""Pydantic models shared across CDC pipeline services."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CdpEventMessage(BaseModel):
    """Emitted by CDC poller for each (fingerprint, ticker) pair."""

    event_key: str = Field(..., description="ArangoDB document _key")
    fingerprint_id: str
    metric_name: str
    ticker: str
    metric_score: float = Field(default=0.0, description="Score from cdp_eventmetric")
    created_at: str = Field(..., description="ISO-8601 timestamp from the tracking event")
    event_data: dict = Field(default_factory=dict, description="Raw eventData from ArangoDB")


class ScoreUpdateMessage(BaseModel):
    """Emitted by scoring consumer after upserting product_recommendations."""

    tenant_id: str
    profile_id: str
    ticker: str
    metric_name: str = Field(default="", description="Source metric that triggered the score update")
    interest_score: float
    raw_score: float
    score_delta: float = Field(default=0.0, description="Change from previous interest_score")
    updated_at: str


class ScoredEventForward(BaseModel):
    """Payload forwarded to external API after scoring."""

    event_key: str
    profile_id: str
    ticker: str
    metric_name: str
    metric_score: float
    interest_score: float
    raw_score: float
    score_delta: float
    created_at: str
    event_data: dict = Field(default_factory=dict, description="Raw eventData from ArangoDB")


class NbaActionMessage(BaseModel):
    """Emitted by NBA publisher after dispatching a channel action."""

    tenant_id: str
    profile_id: str
    ticker: str
    action: str
    channel: str
    confidence: float
    reason: str
    dispatched_at: str
