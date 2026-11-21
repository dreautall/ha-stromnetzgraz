"""Hourly statistics from Stromnetz Graz readings. Pure pandas, no Home Assistant imports."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas


def hourly_frame(df: pandas.DataFrame) -> pandas.DataFrame:
    """Bin readings to full hours (HA statistics are hourly); drops hours without any data.

    CONSUMP is summed, MR (meter reading) takes the hour's maximum and COST is summed.
    MR and COST are optional: the API sometimes returns no meter readings at all.
    """
    agg: dict[str, Any] = {
        "CONSUMP": lambda x: math.nan if len(x) == 0 else sum(x),
    }
    if "MR" in df:
        agg["MR"] = lambda x: math.nan if len(x) == 0 else max(x)
    if "COST" in df:
        agg["COST"] = lambda x: x.sum(min_count=1)
    return (
        df.groupby(pandas.Grouper(freq="h", key="readTime")).agg(agg).dropna(how="all")
    )


def _hour(ts: pandas.Timestamp) -> datetime:
    """HA rejects statistics whose start isn't on a full hour."""
    return ts.to_pydatetime().replace(minute=0, second=0, microsecond=0)


def _value(x: Any) -> float | None:
    """None for missing values; 0 is a valid reading."""
    return None if x is None or x != x else x  # x != x is a NaN check.


def backfill_days(last_start: float, now: float) -> int | None:
    """Days to fetch to reach back to the last stored hour; None while the 30-day window does."""
    days = (now - last_start) / 86400
    return math.ceil(days) + 1 if days > 29 else None


def build_statistics(
    df_hour: pandas.DataFrame,
    base_reading: float | None,
    last_sum: float,
    last_start: float | None,
) -> list[dict[str, Any]]:
    """Turn hourly readings into statistic rows (start, state, sum).

    `last_sum` / `last_start` (POSIX timestamp) describe the stored statistic the
    window starts after: hours up to and including it are skipped and the sum
    continues from it. With a `base_reading` (the meter's first reading) the sum is
    the meter reading minus it, which corrects any drift; hours without a meter
    reading continue from there with their consumption. An hour without consumption
    gets it from the difference of meter readings, if both are known.
    """
    statistics: list[dict[str, Any]] = []
    _sum = last_sum
    # With a base reading, sum == meter reading - base, so the last meter reading is known.
    last_mr = None if base_reading is None else base_reading + last_sum
    for start, data in df_hour.to_dict(orient="index").items():
        consump = _value(data.get("CONSUMP"))
        mr = _value(data.get("MR"))  # e.g. new meters report consumption without it

        if consump is None:
            if mr is None or last_mr is None:
                continue
            consump = mr - last_mr
        if mr is not None:
            last_mr = mr

        start = _hour(start)
        # Compare absolute timestamps: wall-clock times repeat at the end of DST.
        if last_start is not None and start.timestamp() <= last_start:
            continue

        if base_reading is not None and mr is not None:
            _sum = mr - base_reading
        else:
            _sum += consump
        statistics.append({"start": start, "state": consump, "sum": _sum})
    return statistics


def build_cost_statistics(
    costs: pandas.Series, last_sum: float, last_start: float | None
) -> list[dict[str, Any]]:
    """Like build_statistics, for the hourly cost: a running sum over the new hours."""
    statistics: list[dict[str, Any]] = []
    _sum = last_sum
    for start, cost in costs.items():
        start = _hour(start)
        if last_start is not None and start.timestamp() <= last_start:
            continue
        _sum += cost
        statistics.append({"start": start, "state": cost, "sum": _sum})
    return statistics
