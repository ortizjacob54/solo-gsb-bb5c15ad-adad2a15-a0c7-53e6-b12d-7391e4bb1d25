"""End-to-end tests through the HTTP API."""

from datetime import date, datetime, timedelta, timezone

import pytest

from .conftest import make_exhibit

UTC = timezone.utc


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- validation rejections ----------

def test_reject_negative_lux(client, showcase):
    make_exhibit(client, eid="ex-neg")
    resp = client.post(
        "/api/lighting",
        json={
            "exhibit_id": "ex-neg",
            "intervals": [
                {"start_at": "2020-01-10T09:00:00Z",
                 "end_at": "2020-01-10T10:00:00Z", "lux": -5}
            ],
        },
    )
    assert resp.status_code == 422
    assert "lux" in str(resp.json()["detail"])


def test_reject_reversed_interval(client, showcase):
    make_exhibit(client, eid="ex-rev")
    resp = client.post(
        "/api/lighting",
        json={
            "exhibit_id": "ex-rev",
            "intervals": [
                {"start_at": "2020-01-10T12:00:00Z",
                 "end_at": "2020-01-10T09:00:00Z", "lux": 50}
            ],
        },
    )
    assert resp.status_code == 422
    assert "end_at" in str(resp.json()["detail"])


def test_reject_unknown_exhibit(client, showcase):
    resp = client.post(
        "/api/lighting",
        json={
            "exhibit_id": "does-not-exist",
            "intervals": [
                {"start_at": "2020-01-10T09:00:00Z",
                 "end_at": "2020-01-10T10:00:00Z", "lux": 50}
            ],
        },
    )
    assert resp.status_code == 404
    assert "unknown exhibit" in resp.json()["detail"]


def test_reject_exhibit_under_unknown_showcase(client, showcase):
    resp = client.post(
        "/api/exhibits",
        json={
            "id": "ex-homeless",
            "showcase_id": "case-ghost",
            "name": "x",
            "sensitivity": "stable",
        },
    )
    assert resp.status_code == 404
    assert "unknown showcase" in resp.json()["detail"]


def test_reject_empty_interval_list(client, showcase):
    make_exhibit(client, eid="ex-empty")
    resp = client.post("/api/lighting",
                       json={"exhibit_id": "ex-empty", "intervals": []})
    assert resp.status_code == 422


def test_reject_duplicate_ids(client, showcase):
    make_exhibit(client, eid="ex-dup")
    resp = client.post(
        "/api/exhibits",
        json={"id": "ex-dup", "showcase_id": "case-1",
              "name": "x", "sensitivity": "stable"},
    )
    assert resp.status_code == 409
    resp = client.post("/api/showcases", json={"id": "case-1", "name": "x"})
    assert resp.status_code == 409


# ---------- overlap merge (max lux) ----------

def test_overlapping_lamps_merge_with_max_lux(client, showcase):
    # limit 1,000,000 so nothing overruns here
    make_exhibit(client, eid="ex-merge", limit=1_000_000.0)
    resp = client.post(
        "/api/lighting",
        json={
            "exhibit_id": "ex-merge",
            "intervals": [
                # dim lamp 50 lux, 09:00-12:00 (150 lux·h)
                {"start_at": "2020-06-01T09:00:00Z",
                 "end_at": "2020-06-01T12:00:00Z", "lux": 50},
                # bright lamp 200 lux, 10:00-13:00 (overlap -> max=200)
                {"start_at": "2020-06-01T10:00:00Z",
                 "end_at": "2020-06-01T13:00:00Z", "lux": 200},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["stored"] == 2

    tl = [(s["start_at"][11:16], s["end_at"][11:16], s["lux"])
          for s in body["showcase_timeline"]]
    assert tl == [("09:00", "10:00", 50.0),
                  ("10:00", "13:00", 200.0)]

    # 50*1 + 200*3 = 650 lux·h — NOT the naive sum (50*3 + 200*3 = 750)
    assert body["report"]["total_lux_hour"] == pytest.approx(650.0)


def test_merge_takes_max_not_sum_three_lamps(client, showcase):
    make_exhibit(client, eid="ex-three", limit=1e12)
    resp = client.post(
        "/api/lighting",
        json={
            "exhibit_id": "ex-three",
            "intervals": [
                {"start_at": "2020-06-01T00:00:00Z",
                 "end_at": "2020-06-01T04:00:00Z", "lux": 100},
                {"start_at": "2020-06-01T00:00:00Z",
                 "end_at": "2020-06-01T02:00:00Z", "lux": 300},
                {"start_at": "2020-06-01T01:00:00Z",
                 "end_at": "2020-06-01T03:00:00Z", "lux": 200},
            ],
        },
    )
    tl = [(s["start_at"][11:16], s["lux"])
          for s in resp.json()["showcase_timeline"]]
    assert tl == [("00:00", 300.0), ("02:00", 200.0), ("03:00", 100.0)]
    # 300*2 + 200*1 + 100*1 = 900
    assert resp.json()["report"]["total_lux_hour"] == pytest.approx(900.0)


def test_lamps_in_different_showcases_do_not_merge(client, showcase):
    client.post("/api/showcases", json={"id": "case-2", "name": "二号柜"})
    make_exhibit(client, eid="ex-a")
    make_exhibit(client, eid="ex-b", showcase_id="case-2")
    for eid in ("ex-a", "ex-b"):
        client.post(
            "/api/lighting",
            json={"exhibit_id": eid, "intervals": [
                {"start_at": "2020-06-01T09:00:00Z",
                 "end_at": "2020-06-01T11:00:00Z", "lux": 100}]},
        )
    tl_a = client.get(
        "/api/showcases/case-1/timeline",
        params={"day": "2020-06-01"}).json()
    tl_b = client.get(
        "/api/showcases/case-2/timeline",
        params={"day": "2020-06-01"}).json()
    assert len(tl_a) == len(tl_b) == 1
    assert tl_a[0]["lux"] == tl_b[0]["lux"] == 100.0


# ---------- budget overrun ----------

def test_first_overrun_time_and_excess(client, showcase):
    # Annual budget 100 lux·h; lamp 200 lux 09:00-10:00 => 200 lux·h.
    # Crossing happens after 30 min: 2020-01-10 09:30:00Z, excess 100.
    make_exhibit(client, eid="ex-over", limit=100.0)
    resp = client.post(
        "/api/lighting",
        json={"exhibit_id": "ex-over", "intervals": [
            {"start_at": "2020-01-10T09:00:00Z",
             "end_at": "2020-01-10T10:00:00Z", "lux": 200}]},
    )
    report = resp.json()["report"]
    assert report["first_overrun_at"] == "2020-01-10T09:30:00Z"
    assert report["over_lux_hour"] == pytest.approx(100.0)
    assert report["annual_remaining_lux_hour"] == 0.0


def test_partial_overrun_inside_segment(client, showcase):
    # 60 lux for 1h = 60 (within 100), then 100 lux for another hour:
    # need 40 more -> crossing 24 min into the second segment.
    make_exhibit(client, eid="ex-over2", limit=100.0)
    resp = client.post(
        "/api/lighting",
        json={"exhibit_id": "ex-over2", "intervals": [
            {"start_at": "2020-01-10T09:00:00Z",
             "end_at": "2020-01-10T10:00:00Z", "lux": 60},
            {"start_at": "2020-01-10T10:00:00Z",
             "end_at": "2020-01-10T11:00:00Z", "lux": 100}]},
    )
    report = resp.json()["report"]
    assert report["first_overrun_at"] == "2020-01-10T10:24:00Z"
    assert report["over_lux_hour"] == pytest.approx(60.0)


def test_no_overrun_when_under_budget(client, showcase):
    make_exhibit(client, eid="ex-ok", limit=500.0)
    resp = client.post(
        "/api/lighting",
        json={"exhibit_id": "ex-ok", "intervals": [
            {"start_at": "2020-01-10T09:00:00Z",
             "end_at": "2020-01-10T10:00:00Z", "lux": 100}]},
    )
    report = resp.json()["report"]
    assert report["first_overrun_at"] is None
    assert report["over_lux_hour"] == pytest.approx(0.0)
    assert report["annual_remaining_lux_hour"] == pytest.approx(400.0)


def test_stable_exhibit_has_no_budget_cap(client, showcase):
    make_exhibit(client, eid="ex-stable", sensitivity="stable")
    # create without explicit limit -> category default (stable => null)
    got = client.get("/api/exhibits/ex-stable").json()
    assert got["annual_limit_lux_hour"] is None

    resp = client.post(
        "/api/lighting",
        json={"exhibit_id": "ex-stable", "intervals": [
            {"start_at": "2020-01-10T08:00:00Z",
             "end_at": "2020-01-10T18:00:00Z", "lux": 5000}]},
    )
    report = resp.json()["report"]
    assert report["annual_limit_lux_hour"] is None
    assert report["first_overrun_at"] is None
    assert report["over_lux_hour"] is None
    assert report["daily"]["remaining_lux_hour"] is None
    assert report["daily"]["remaining_hours_at_max_lux"] is None


def test_sensitivity_defaults(client, showcase):
    make_exhibit(client, eid="ex-high", sensitivity="high_sensitivity")
    got = client.get("/api/exhibits/ex-high").json()
    assert got["annual_limit_lux_hour"] == 15000.0
    make_exhibit(client, eid="ex-med", sensitivity="medium_sensitivity")
    got = client.get("/api/exhibits/ex-med").json()
    assert got["annual_limit_lux_hour"] == 150000.0


# ---------- queries ----------

def test_query_showcase_timeline_by_date(client, showcase):
    make_exhibit(client, eid="ex-q1", limit=1e12)
    client.post("/api/lighting", json={"exhibit_id": "ex-q1", "intervals": [
        {"start_at": "2020-06-01T23:00:00Z",
         "end_at": "2020-06-02T01:00:00Z", "lux": 50}]})

    day1 = client.get("/api/showcases/case-1/timeline",
                      params={"day": "2020-06-01"}).json()
    day2 = client.get("/api/showcases/case-1/timeline",
                      params={"day": "2020-06-02"}).json()
    other = client.get("/api/showcases/case-1/timeline",
                       params={"day": "2020-06-03"}).json()
    assert len(day1) == len(day2) == 1
    assert other == []
    assert day1[0]["lux_hour"] == pytest.approx(50.0)  # 50 lux * 1 h
    assert day2[0]["lux_hour"] == pytest.approx(50.0)


def test_query_exhibit_report_by_date(client, showcase):
    make_exhibit(client, eid="ex-q2", limit=1e12)
    client.post("/api/lighting", json={"exhibit_id": "ex-q2", "intervals": [
        {"start_at": "2020-06-01T09:00:00Z",
         "end_at": "2020-06-01T12:00:00Z", "lux": 100}]})
    resp = client.get("/api/exhibits/ex-q2/report",
                      params={"day": "2020-06-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["segments"]) == 1
    assert body["report"]["annual_lux_hour"] == pytest.approx(300.0)
    # Querying another day: no segments but report still computed.
    resp2 = client.get("/api/exhibits/ex-q2/report",
                       params={"day": "2020-07-01"})
    assert resp2.json()["segments"] == []


def test_timeline_without_date_returns_everything(client, showcase):
    make_exhibit(client, eid="ex-q3", limit=1e12)
    client.post("/api/lighting", json={"exhibit_id": "ex-q3", "intervals": [
        {"start_at": "2019-01-01T09:00:00Z",
         "end_at": "2019-01-01T10:00:00Z", "lux": 10}]})
    client.post("/api/lighting", json={"exhibit_id": "ex-q3", "intervals": [
        {"start_at": "2025-06-01T09:00:00Z",
         "end_at": "2025-06-01T10:00:00Z", "lux": 20}]})
    tl = client.get("/api/showcases/case-1/timeline").json()
    assert len(tl) == 2
    assert {s["lux"] for s in tl} == {10.0, 20.0}


def test_timeline_unknown_showcase_404(client):
    assert client.get("/api/showcases/nope/timeline").status_code == 404
    assert client.get("/api/exhibits/nope/report",
                      params={"day": "2020-01-01"}).status_code == 404


# ---------- daily remaining allowance ----------

def test_daily_remaining_for_past_day(client, showcase):
    # 36600 lux·h annual budget (2020 is a leap year) -> 100 lux·h per day.
    make_exhibit(client, eid="ex-day", limit=36600.0)
    client.post("/api/lighting", json={"exhibit_id": "ex-day", "intervals": [
        # 2020-01-10 09:00-10:00 at 50 lux = 50 lux·h
        {"start_at": "2020-01-10T09:00:00Z",
         "end_at": "2020-01-10T10:00:00Z", "lux": 50}]})
    body = client.get("/api/exhibits/ex-day/report",
                      params={"day": "2020-01-10"}).json()
    daily = body["report"]["daily"]
    assert daily["date"] == "2020-01-10"
    assert daily["budget_lux_hour"] == pytest.approx(100.0)
    assert daily["used_lux_hour"] == pytest.approx(50.0)
    assert daily["remaining_lux_hour"] == pytest.approx(50.0)
    # brightest lamp of the day = 50 lux -> 1 more hour possible
    assert daily["remaining_hours_at_max_lux"] == pytest.approx(1.0)
    assert daily["max_lux_today"] == 50.0


def test_daily_remaining_capped_by_annual_remainder(client, showcase):
    # 100 lux·h total annual budget -> day share tiny; after burning all,
    # remaining is zero even though the queried day itself is untouched.
    make_exhibit(client, eid="ex-cap", limit=100.0)
    client.post("/api/lighting", json={"exhibit_id": "ex-cap", "intervals": [
        {"start_at": "2020-01-01T09:00:00Z",
         "end_at": "2020-01-01T11:00:00Z", "lux": 100}]})  # 200 lux·h
    body = client.get("/api/exhibits/ex-cap/report",
                      params={"day": "2020-12-31"}).json()
    daily = body["report"]["daily"]
    assert daily["used_lux_hour"] == 0.0  # that day had no lighting
    assert daily["remaining_lux_hour"] == 0.0  # annual budget exhausted


def test_future_planned_light_not_counted_as_used_today(client, showcase):
    make_exhibit(client, eid="ex-fut", limit=365000.0)
    # A lamp planned later today (relative to real "now") should not be
    # counted as used exposure yet.
    now = datetime.now(UTC)
    start = (now + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    client.post("/api/lighting", json={"exhibit_id": "ex-fut", "intervals": [
        {"start_at": _iso(start), "end_at": _iso(end), "lux": 100}]})
    body = client.get(
        "/api/exhibits/ex-fut/report",
        params={"day": now.date().isoformat()}).json()
    daily = body["report"]["daily"]
    assert daily["used_lux_hour"] == 0.0
    assert daily["max_lux_today"] == 100.0
    assert daily["remaining_lux_hour"] > 0.0


# ---------- persistence ----------

def test_data_persists_in_database(client, showcase):
    make_exhibit(client, eid="ex-persist", limit=1e9)
    client.post("/api/lighting", json={"exhibit_id": "ex-persist", "intervals": [
        {"start_at": "2020-03-03T09:00:00Z",
         "end_at": "2020-03-03T10:00:00Z", "lux": 42}]})
    # A brand new client (same DB file) sees previously stored intervals.
    from fastapi.testclient import TestClient
    from app.main import app
    fresh = TestClient(app)
    tl = fresh.get("/api/showcases/case-1/timeline",
                   params={"day": "2020-03-03"}).json()
    assert any(s["lux"] == 42.0 for s in tl)
