"""Exposure budgeting: cumulative lux·hour consumption and overrun analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

from .timeline import Segment, clip_segments, day_bounds, total_lux_hours

EPS = 1e-9  # tolerance: strictly above the budget counts as overrun


@dataclass(frozen=True)
class DailyAllowance:
    """Remaining lighting allowance for a day at the queried instant."""

    date: date
    budget_lux_hour: float | None
    used_lux_hour: float
    remaining_lux_hour: float | None
    remaining_hours_at_max_lux: float | None
    max_lux_today: float


def _find_overrun(
    segments: Sequence[Segment], limit: float
) -> tuple[datetime | None, float]:
    """Walk merged segments accumulating lux·hours.

    Returns the first instant at which the cumulative exposure crosses
    ``limit`` and the amount by which the period's total exceeds it.
    """
    acc = 0.0
    for seg in segments:
        exposure = seg.lux * seg.hours
        if exposure <= 0:
            continue
        if acc + exposure <= limit + EPS:
            acc += exposure
            continue
        need = limit - acc
        crossing = seg.start + timedelta(hours=need / seg.lux)
        return crossing, max(0.0, acc + exposure - limit)
    return None, max(0.0, acc - limit)


def annual_window(day: date) -> tuple[datetime, datetime]:
    """[Jan 1, next Jan 1) UTC bounds of the calendar year containing ``day``."""
    return day_bounds(date(day.year, 1, 1))[0], day_bounds(
        date(day.year + 1, 1, 1)
    )[0]


def daily_allowance(
    segments: Sequence[Segment],
    day: date,
    annual_limit: float | None,
    annual_remaining: float | None,
    now: datetime,
) -> DailyAllowance:
    """Remaining budget for ``day``.

    The day's *budget* is the annual budget spread evenly over the
    365/366 days of the year.  "Used" counts light delivered up to
    ``now`` (future, merely-planned intervals are not spent yet).
    The *remaining* quota is bounded by both the per-day share and the
    annual remainder (so a day cannot spend budget reserved by planned
    lighting on other days).  ``remaining_hours_at_max_lux`` answers
    "how much longer can today's brightest lamp stay on".
    """
    lo, hi = day_bounds(day)
    day_segments = clip_segments(segments, lo, hi)
    used = total_lux_hours(clip_segments(day_segments, lo, min(hi, now)))
    max_lux = max((s.lux for s in day_segments), default=0.0)

    if annual_limit is None or annual_remaining is None:
        budget = remaining = hours_left = None
    else:
        days = 366 if _is_leap(day.year) else 365
        budget = annual_limit / days
        remaining = max(0.0, min(budget - used, annual_remaining))
        hours_left = round(remaining / max_lux, 6) if max_lux > 0 else None

    return DailyAllowance(
        date=day,
        budget_lux_hour=budget,
        used_lux_hour=round(used, 6),
        remaining_lux_hour=remaining,
        remaining_hours_at_max_lux=hours_left,
        max_lux_today=max_lux,
    )


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def build_annual_report(
    segments: Sequence[Segment],
    annual_limit: float | None,
    reference_day: date,
    now: datetime | None = None,
) -> dict:
    """Assemble the annual exposure report for one exhibit.

    Fields:
      * total_lux_hour  – exposure over every stored interval
      * annual_lux_hour – exposure inside ``reference_day``'s calendar year
      * first_overrun_at / over_lux_hour – first budget breach (in year)
      * daily – remaining allowance for ``reference_day``
    """
    now = now or datetime.now(timezone.utc)
    total = total_lux_hours(segments)
    ylo, yhi = annual_window(reference_day)
    year_segments = clip_segments(segments, ylo, yhi)
    year_used = total_lux_hours(year_segments)

    if annual_limit is None:
        over_at: datetime | None = None
        over = None
        annual_remaining: float | None = None
    else:
        over_at, over = _find_overrun(year_segments, annual_limit)
        annual_remaining = max(0.0, annual_limit - year_used)

    daily = daily_allowance(
        segments, reference_day, annual_limit, annual_remaining, now
    )
    return {
        "total_lux_hour": round(total, 6),
        "annual_year": reference_day.year,
        "annual_lux_hour": round(year_used, 6),
        "annual_limit_lux_hour": annual_limit,
        "annual_remaining_lux_hour": (
            round(annual_remaining, 6) if annual_remaining is not None else None
        ),
        "first_overrun_at": over_at.isoformat() if over_at else None,
        "over_lux_hour": round(over, 6) if over is not None else None,
        "daily": {
            "date": daily.date.isoformat(),
            "budget_lux_hour": (
                round(daily.budget_lux_hour, 6)
                if daily.budget_lux_hour is not None
                else None
            ),
            "used_lux_hour": daily.used_lux_hour,
            "remaining_lux_hour": daily.remaining_lux_hour,
            "remaining_hours_at_max_lux": daily.remaining_hours_at_max_lux,
            "max_lux_today": daily.max_lux_today,
        },
    }
