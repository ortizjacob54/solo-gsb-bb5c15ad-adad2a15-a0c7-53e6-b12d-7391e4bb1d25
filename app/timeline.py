"""Timeline arithmetic for showcase lighting.

The key operation is *merging* the lighting intervals of a showcase:
when two lamps overlap in time the illuminance on every exhibit inside
that showcase is the **maximum** of the overlapping lux values, not the
sum.  A classic sweep-line over interval endpoints produces the merged
segments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RawInterval:
    """One submitted lighting interval (lamp on between start/end)."""

    start: datetime
    end: datetime
    lux: float


@dataclass(frozen=True)
class Segment:
    """A merged piece of the timeline with a constant max illuminance."""

    start: datetime
    end: datetime
    lux: float

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


def parse_dt(value: str | datetime) -> datetime:
    """Parse an ISO-8601 string and normalise it to aware UTC."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def merge_intervals(intervals: Iterable[RawInterval]) -> list[Segment]:
    """Merge overlapping intervals; lux on overlap = max of active lamps.

    Adjacent segments that carry the same lux are glued together so a
    steady lamp yields one segment instead of many zero-width pieces.
    """
    # (instant, kind, lux); kind 1 = turn off, 2 = turn on.
    # At the same instant an "off" is processed first: a lamp ending at
    # t never contributes light at t while a lamp starting at t does.
    events: list[tuple[datetime, int, float]] = []
    for iv in intervals:
        if iv.end < iv.start:
            raise ValueError("interval end is before start")
        if iv.lux < 0:
            raise ValueError("lux must not be negative")
        if iv.end == iv.start:
            continue  # zero-length interval contributes nothing
        events.append((iv.start, 2, iv.lux))
        events.append((iv.end, 1, iv.lux))
    if not events:
        return []
    events.sort(key=lambda e: (e[0], e[1]))

    active: dict[float, int] = {}
    segments: list[Segment] = []
    prev_t = events[0][0]

    def emit(end: datetime, lux: float) -> None:
        if end <= prev_t or lux <= 0:
            return  # zero-width or darkness is not a lit segment
        if segments and segments[-1].end == prev_t and segments[-1].lux == lux:
            segments[-1] = Segment(segments[-1].start, end, lux)
        else:
            segments.append(Segment(prev_t, end, lux))

    for t, kind, lux in events:
        cur = max(active) if active else 0.0
        emit(t, cur)
        if kind == 2:
            active[lux] = active.get(lux, 0) + 1
        else:
            count = active.get(lux, 0) - 1
            if count > 0:
                active[lux] = count
            else:
                active.pop(lux, None)
        prev_t = t
    return segments


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC [start, end) bounds of a calendar day."""
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def clip_segments(
    segments: Sequence[Segment], lo: datetime, hi: datetime
) -> list[Segment]:
    """Return the parts of ``segments`` intersecting [lo, hi)."""
    out: list[Segment] = []
    for seg in segments:
        s, e = max(seg.start, lo), min(seg.end, hi)
        if e > s and seg.lux > 0:
            out.append(Segment(s, e, seg.lux))
    return out


def total_lux_hours(segments: Iterable[Segment]) -> float:
    return sum(seg.lux * seg.hours for seg in segments)
