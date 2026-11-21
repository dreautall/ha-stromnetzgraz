"""Run with: uvx --with pandas --with aiohttp --with pyjwt pytest tests/"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas
import pytest

# Load stats.py on its own: importing the package would pull in Home Assistant.
_spec = importlib.util.spec_from_file_location(
    "stats", Path(__file__).parents[1] / "custom_components/stromnetzgraz/stats.py"
)
stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats)

T0 = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
NAN = float("nan")


def frame(rows):
    """rows: (offset in hours, CONSUMP, MR or None)."""
    data = {
        "readTime": [T0 + timedelta(hours=h) for h, _, _ in rows],
        "CONSUMP": [c for _, c, _ in rows],
    }
    if any(mr is not None for _, _, mr in rows):
        data["MR"] = [NAN if mr is None else mr for _, _, mr in rows]
    return stats.hourly_frame(pandas.DataFrame(data))


def build(df_hour, base=None, last_sum=0.0, last_start=None):
    return [
        (r["start"], r["state"], r["sum"])
        for r in stats.build_statistics(df_hour, base, last_sum, last_start)
    ]


def test_hourly_frame_bins_quarter_hours():
    df = pandas.DataFrame(
        {
            "readTime": [T0 + timedelta(minutes=15 * i) for i in range(8)],
            "CONSUMP": [1.0] * 8,
            "MR": [100.0 + i for i in range(8)],
        }
    )
    hourly = stats.hourly_frame(df)
    assert list(hourly["CONSUMP"]) == [4.0, 4.0]
    assert list(hourly["MR"]) == [103.0, 107.0]


def test_hourly_frame_without_meter_readings():
    assert "MR" not in frame([(0, 1.0, None)])


def test_sum_accumulates_from_last_sum():
    rows = build(frame([(0, 1.0, None), (1, 2.0, None)]), last_sum=10.0)
    assert [(s, c) for _, s, c in rows] == [(1.0, 11.0), (2.0, 13.0)]
    assert rows[0][0] == T0


def test_skips_hours_up_to_last_start():
    rows = build(
        frame([(0, 1.0, None), (1, 2.0, None), (2, 3.0, None)]),
        last_start=(T0 + timedelta(hours=1)).timestamp(),
    )
    assert [r[0] for r in rows] == [T0 + timedelta(hours=2)]


def test_dst_repeated_hour_is_not_skipped():
    """On 2026-10-25 Vienna has 02:00 twice (CEST, then CET): both must be kept."""
    vienna = pandas.Timestamp("2026-10-25 00:00", tz="Europe/Vienna")
    times = [vienna + pandas.Timedelta(hours=h) for h in range(5)]
    df_hour = pandas.DataFrame({"CONSUMP": [1.0] * 5}, index=pandas.DatetimeIndex(times))
    rows = stats.build_statistics(df_hour, None, 0.0, None)
    assert len(rows) == 5
    # Only the first 02:00 (CEST) is stored: the second one must still come through.
    rows = stats.build_statistics(df_hour, None, 0.0, times[2].timestamp())
    assert [r["start"].timestamp() for r in rows] == [t.timestamp() for t in times[3:]]


def test_base_reading_makes_sum_the_meter_reading():
    rows = build(frame([(0, 1.0, 1001.0), (1, 2.0, 1003.0)]), base=1000.0)
    assert [r[2] for r in rows] == [1.0, 3.0]


def test_missing_consumption_is_derived_from_meter_reading():
    df_hour = pandas.DataFrame(
        {"CONSUMP": [NAN], "MR": [1005.0]},
        index=pandas.DatetimeIndex([T0]),
    )
    rows = build(df_hour, base=1000.0, last_sum=2.0)  # last meter reading: 1002
    assert [(r[1], r[2]) for r in rows] == [(3.0, 5.0)]


def test_missing_consumption_without_any_meter_reading_is_skipped():
    df_hour = pandas.DataFrame(
        {"CONSUMP": [NAN, 1.0], "MR": [1005.0, 1006.0]},
        index=pandas.DatetimeIndex([T0, T0 + timedelta(hours=1)]),
    )
    rows = build(df_hour)
    assert [r[1] for r in rows] == [1.0]


def test_nan_meter_reading_falls_back_to_consumption_sum():
    rows = build(frame([(0, 1.0, None), (1, 2.0, 1003.0)]), base=1000.0)
    assert [r[2] for r in rows] == [1.0, 3.0]


def test_cost_statistics_sum_and_skip():
    costs = pandas.Series(
        [0.5, 1.0, 2.0],
        index=pandas.DatetimeIndex([T0 + timedelta(hours=h) for h in range(3)]),
    )
    rows = stats.build_cost_statistics(costs, 10.0, T0.timestamp())
    assert [(r["state"], r["sum"]) for r in rows] == [(1.0, 11.0), (2.0, 13.0)]


def test_zero_consumption_is_a_value():
    """A 0 kWh hour must not be treated as missing (it used to become MR - sum)."""
    rows = build(frame([(0, 1.0, 25001.0), (1, 0.0, 25001.0), (2, 1.0, None)]),
                 base=20000.0, last_sum=5000.0)
    assert [(r[1], r[2]) for r in rows] == [(1.0, 5001.0), (0.0, 5001.0), (1.0, 5002.0)]


def test_base_reading_zero_is_used():
    """A brand-new meter can start at 0: that's a base reading, not a missing one."""
    rows = build(frame([(0, 1.0, 1.0), (1, 2.0, 3.0)]), base=0.0)
    assert [r[2] for r in rows] == [1.0, 3.0]


def test_zero_meter_reading_is_a_value():
    df_hour = pandas.DataFrame(
        {"CONSUMP": [NAN, NAN], "MR": [0.0, 2.0]},
        index=pandas.DatetimeIndex([T0, T0 + timedelta(hours=1)]),
    )
    assert [(r[1], r[2]) for r in build(df_hour, base=0.0)] == [(0.0, 0.0), (2.0, 2.0)]


def test_consumption_derived_from_consecutive_meter_readings_without_base():
    df_hour = pandas.DataFrame(
        {"CONSUMP": [1.0, NAN], "MR": [1001.0, 1004.0]},
        index=pandas.DatetimeIndex([T0, T0 + timedelta(hours=1)]),
    )
    assert [(r[1], r[2]) for r in build(df_hour, last_sum=10.0)] == [(1.0, 11.0), (3.0, 14.0)]


def test_backfill_only_beyond_the_30_day_window():
    now = T0.timestamp()
    assert stats.backfill_days(now - 10 * 86400, now) is None
    assert stats.backfill_days(now - 40.5 * 86400, now) == 42
