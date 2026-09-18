"""Repository / service layer: persistence access + report assembly."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Iterable

from . import database
from .budget import build_annual_report
from .database import DEFAULT_ANNUAL_LIMIT
from .schemas import (
    ExhibitCreate,
    ExhibitOut,
    LightingRequest,
    SegmentOut,
    Sensitivity,
    ShowcaseCreate,
    ShowcaseOut,
)
from .timeline import (
    RawInterval,
    Segment,
    clip_segments,
    day_bounds,
    merge_intervals,
    parse_dt,
    total_lux_hours,
)


class NotFound(Exception):
    """Referenced showcase/exhibit does not exist (maps to HTTP 404)."""


class Conflict(Exception):
    """Primary key already exists (maps to HTTP 409)."""


# ---------------- helpers ----------------

def _row_to_showcase(row: sqlite3.Row) -> ShowcaseOut:
    return ShowcaseOut(
        id=row["id"], name=row["name"], created_at=parse_dt(row["created_at"])
    )


def _row_to_exhibit(row: sqlite3.Row) -> ExhibitOut:
    return ExhibitOut(
        id=row["id"],
        showcase_id=row["showcase_id"],
        name=row["name"],
        sensitivity=Sensitivity(row["sensitivity"]),
        annual_limit_lux_hour=row["annual_limit_lux_hour"],
        created_at=parse_dt(row["created_at"]),
    )


def _segment_out(seg: Segment) -> SegmentOut:
    return SegmentOut(
        start_at=seg.start,
        end_at=seg.end,
        lux=seg.lux,
        lux_hour=round(seg.lux * seg.hours, 6),
    )


def _resolve_limit(payload: ExhibitCreate) -> float | None:
    # An explicitly provided value wins; otherwise the category default.
    if payload.annual_limit_lux_hour is not None:
        return float(payload.annual_limit_lux_hour)
    return DEFAULT_ANNUAL_LIMIT[payload.sensitivity.value]


def get_showcase(conn: sqlite3.Connection, showcase_id: str) -> ShowcaseOut:
    row = conn.execute(
        "SELECT * FROM showcases WHERE id = ?", (showcase_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"unknown showcase: {showcase_id}")
    return _row_to_showcase(row)


def get_exhibit(conn: sqlite3.Connection, exhibit_id: str) -> ExhibitOut:
    row = conn.execute(
        "SELECT * FROM exhibits WHERE id = ?", (exhibit_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"unknown exhibit: {exhibit_id}")
    return _row_to_exhibit(row)


def merged_showcase_segments(
    conn: sqlite3.Connection, showcase_id: str
) -> list[Segment]:
    """All lighting intervals of a showcase merged on the same timeline."""
    rows = conn.execute(
        """SELECT start_at, end_at, lux FROM lighting_intervals
           WHERE showcase_id = ? ORDER BY start_at""",
        (showcase_id,),
    ).fetchall()
    raw = [
        RawInterval(parse_dt(r["start_at"]), parse_dt(r["end_at"]), r["lux"])
        for r in rows
    ]
    return merge_intervals(raw)


def _insert_intervals(
    conn: sqlite3.Connection,
    showcase_id: str,
    exhibit_id: str,
    intervals: Iterable,
) -> int:
    n = 0
    for iv in intervals:
        conn.execute(
            """INSERT INTO lighting_intervals
                   (showcase_id, exhibit_id, start_at, end_at, lux)
               VALUES (?, ?, ?, ?, ?)""",
            (
                showcase_id,
                exhibit_id,
                iv.start_at.astimezone(timezone.utc).isoformat(),
                iv.end_at.astimezone(timezone.utc).isoformat(),
                iv.lux,
            ),
        )
        n += 1
    return n


# ---------------- write operations ----------------

def create_showcase(conn: sqlite3.Connection, payload: ShowcaseCreate) -> ShowcaseOut:
    now = datetime.now(timezone.utc)
    try:
        conn.execute(
            "INSERT INTO showcases (id, name, created_at) VALUES (?, ?, ?)",
            (payload.id, payload.name, now.isoformat()),
        )
    except sqlite3.IntegrityError:
        raise Conflict(f"showcase already exists: {payload.id}")
    return get_showcase(conn, payload.id)


def create_exhibit(conn: sqlite3.Connection, payload: ExhibitCreate) -> ExhibitOut:
    get_showcase(conn, payload.showcase_id)  # 404 if case missing
    now = datetime.now(timezone.utc)
    limit = _resolve_limit(payload)
    try:
        conn.execute(
            """INSERT INTO exhibits
                   (id, showcase_id, name, sensitivity,
                    annual_limit_lux_hour, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                payload.id,
                payload.showcase_id,
                payload.name,
                payload.sensitivity.value,
                limit,
                now.isoformat(),
            ),
        )
    except sqlite3.IntegrityError:
        raise Conflict(f"exhibit already exists: {payload.id}")
    _insert_intervals(conn, payload.showcase_id, payload.id, payload.intervals)
    return get_exhibit(conn, payload.id)


def add_lighting(
    conn: sqlite3.Connection, payload: LightingRequest
) -> tuple[ExhibitOut, int, list[Segment]]:
    exhibit = get_exhibit(conn, payload.exhibit_id)  # 404 unknown exhibit
    n = _insert_intervals(
        conn, exhibit.showcase_id, exhibit.id, payload.intervals
    )
    segments = merged_showcase_segments(conn, exhibit.showcase_id)
    return exhibit, n, segments


# ---------------- read operations ----------------

def showcase_timeline(
    conn: sqlite3.Connection, showcase_id: str, day: date | None
) -> tuple[ShowcaseOut, list[Segment]]:
    showcase = get_showcase(conn, showcase_id)
    segments = merged_showcase_segments(conn, showcase_id)
    if day is not None:
        lo, hi = day_bounds(day)
        segments = clip_segments(segments, lo, hi)
    return showcase, segments


def exhibit_report(
    conn: sqlite3.Connection, exhibit_id: str, day: date
) -> tuple[ExhibitOut, dict, list[Segment]]:
    exhibit = get_exhibit(conn, exhibit_id)
    segments = merged_showcase_segments(conn, exhibit.showcase_id)
    day_segments = clip_segments(segments, *day_bounds(day))
    report = build_annual_report(segments, exhibit.annual_limit_lux_hour, day)
    return exhibit, report, day_segments


def report_for_segments(exhibit: ExhibitOut, segments: list[Segment], day: date) -> dict:
    return build_annual_report(segments, exhibit.annual_limit_lux_hour, day)


def segments_to_out(segments: Iterable[Segment]) -> list[SegmentOut]:
    return [_segment_out(s) for s in segments]


def timeline_total(segments: Iterable[Segment]) -> float:
    return total_lux_hours(segments)


# re-export for routers/tests
__all__ = [
    "NotFound",
    "Conflict",
    "create_showcase",
    "create_exhibit",
    "add_lighting",
    "get_showcase",
    "get_exhibit",
    "showcase_timeline",
    "exhibit_report",
    "merged_showcase_segments",
    "report_for_segments",
    "segments_to_out",
    "timeline_total",
    "database",
]
