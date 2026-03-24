"""Pydantic models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class FocusEvent(BaseModel):
    type: Literal["focus"]
    url: str
    title: str | None = None
    tab_id: int | None = None
    timestamp: datetime


class BlurEvent(BaseModel):
    type: Literal["blur"]
    url: str
    tab_id: int | None = None
    timestamp: datetime


ObservationEvent = FocusEvent | BlurEvent
