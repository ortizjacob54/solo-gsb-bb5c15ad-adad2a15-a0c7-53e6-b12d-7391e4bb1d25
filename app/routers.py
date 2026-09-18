"""HTTP API routes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import sqlite3
from fastapi import APIRouter, Depends, Query

from . import repository as repo
from .database import get_conn
from .schemas import (
    AnnualReportOut,
    ExhibitCreate,
    ExhibitOut,
    ExhibitReportOut,
    LightingRequest,
    LightingResponse,
    ShowcaseCreate,
    ShowcaseOut,
    SegmentOut,
)

router = APIRouter(prefix="/api")


# ---------- showcases ----------

@router.post("/showcases", response_model=ShowcaseOut, status_code=201,
             tags=["showcases"])
def create_showcase(payload: ShowcaseCreate,
                    conn: sqlite3.Connection = Depends(get_conn)):
    return repo.create_showcase(conn, payload)


@router.get("/showcases/{showcase_id}", response_model=ShowcaseOut,
            tags=["showcases"])
def get_showcase(showcase_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    return repo.get_showcase(conn, showcase_id)


@router.get("/showcases/{showcase_id}/timeline",
            response_model=list[SegmentOut], tags=["showcases"])
def showcase_timeline(
    showcase_id: str,
    day: Optional[date] = Query(
        None, description="只返回该 UTC 日期（YYYY-MM-DD）的区段；省略返回全部"
    ),
    conn: sqlite3.Connection = Depends(get_conn),
):
    _, segments = repo.showcase_timeline(conn, showcase_id, day)
    return repo.segments_to_out(segments)


# ---------- exhibits ----------

@router.post("/exhibits", response_model=ExhibitOut, status_code=201,
             tags=["exhibits"])
def create_exhibit(payload: ExhibitCreate,
                   conn: sqlite3.Connection = Depends(get_conn)):
    return repo.create_exhibit(conn, payload)


@router.get("/exhibits/{exhibit_id}", response_model=ExhibitOut,
            tags=["exhibits"])
def get_exhibit(exhibit_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    return repo.get_exhibit(conn, exhibit_id)


@router.get("/exhibits/{exhibit_id}/report",
            response_model=ExhibitReportOut, tags=["exhibits"])
def exhibit_report(
    exhibit_id: str,
    day: date = Query(
        ..., description="查询日期 YYYY-MM-DD（UTC），决定年度窗口与每日额度"
    ),
    conn: sqlite3.Connection = Depends(get_conn),
):
    exhibit, report, day_segments = repo.exhibit_report(conn, exhibit_id, day)
    return {
        "exhibit": exhibit,
        "report": AnnualReportOut(**report),
        "segments": repo.segments_to_out(day_segments),
    }


# ---------- lighting intervals ----------

@router.post("/lighting", response_model=LightingResponse, status_code=201,
             tags=["lighting"])
def submit_lighting(payload: LightingRequest,
                    conn: sqlite3.Connection = Depends(get_conn)):
    exhibit, stored, segments = repo.add_lighting(conn, payload)
    # Daily allowance is reported against the first interval's day.
    first_day = payload.intervals[0].start_at.astimezone(timezone.utc).date()
    report = repo.report_for_segments(exhibit, segments, first_day)
    return {
        "stored": stored,
        "exhibit": exhibit,
        "report": AnnualReportOut(**report),
        "showcase_timeline": repo.segments_to_out(segments),
    }
