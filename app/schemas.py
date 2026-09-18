"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Sensitivity(str, Enum):
    """Light-sensitivity category of an exhibit (CIE 157)."""

    high_sensitivity = "high_sensitivity"      # textiles, paper, dyes
    medium_sensitivity = "medium_sensitivity"  # oil paintings, wood, bone
    stable = "stable"                          # metal, stone, ceramics


# ---------------- showcases ----------------

class ShowcaseCreate(BaseModel):
    id: str = Field(..., min_length=1, examples=["case-a"])
    name: str = Field(..., min_length=1, examples=["书画厅 A 号展柜"])


class ShowcaseOut(BaseModel):
    id: str
    name: str
    created_at: datetime


# ---------------- exhibits ----------------

class IntervalIn(BaseModel):
    start_at: datetime = Field(..., examples=["2026-01-10T09:00:00Z"])
    end_at: datetime = Field(..., examples=["2026-01-10T17:00:00Z"])
    lux: float = Field(..., ge=0, description="Illuminance in lux, must be >= 0")

    @model_validator(mode="after")
    def _check_order(self) -> "IntervalIn":
        if self.end_at < self.start_at:
            raise ValueError("end_at must not be earlier than start_at")
        return self


class ExhibitCreate(BaseModel):
    id: str = Field(..., min_length=1)
    showcase_id: str
    name: str = Field(..., min_length=1)
    sensitivity: Sensitivity
    # Omit to take the sensitivity-category default; null means "no cap".
    annual_limit_lux_hour: Optional[float] = Field(default=None, ge=0)
    intervals: list[IntervalIn] = Field(default_factory=list)


class ExhibitOut(BaseModel):
    id: str
    showcase_id: str
    name: str
    sensitivity: Sensitivity
    annual_limit_lux_hour: Optional[float]
    created_at: datetime


# ---------------- lighting submissions ----------------

class LightingRequest(BaseModel):
    exhibit_id: str
    intervals: list[IntervalIn] = Field(..., min_length=1)


class SegmentOut(BaseModel):
    start_at: datetime
    end_at: datetime
    lux: float
    lux_hour: float


class DailyOut(BaseModel):
    date: str
    budget_lux_hour: Optional[float]
    used_lux_hour: float
    remaining_lux_hour: Optional[float]
    remaining_hours_at_max_lux: Optional[float]
    max_lux_today: float


class AnnualReportOut(BaseModel):
    total_lux_hour: float
    annual_year: int
    annual_lux_hour: float
    annual_limit_lux_hour: Optional[float]
    annual_remaining_lux_hour: Optional[float]
    first_overrun_at: Optional[datetime]
    over_lux_hour: Optional[float]
    daily: DailyOut


class ExhibitReportOut(BaseModel):
    exhibit: ExhibitOut
    report: AnnualReportOut
    segments: list[SegmentOut]


class LightingResponse(BaseModel):
    stored: int
    exhibit: ExhibitOut
    report: AnnualReportOut
    showcase_timeline: list[SegmentOut]
