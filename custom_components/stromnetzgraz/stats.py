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


def build_statistics(
    df_hour: pandas.DataFrame,
    base_reading: float,
    last_sum: float,
    last_start: float | None,
) -> list[dict[str, Any]]:
    """Turn hourly readings into statistic rows (start, state, sum).

    `last_sum` / `last_start` (POSIX timestamp) describe the newest stored statistic:
    hours up to and including it are skipped and the sum continues from it. With a
    `base_reading` the sum is the meter reading minus it, which self-corrects drift.
    Without one, hours lacking consumption are skipped: a derived value is too unreliable.
    """
    statistics: list[dict[str, Any]] = []
    _sum = last_sum
    last_reading = last_sum
    for start, data in df_hour.to_dict(orient="index").items():
        consump = data.get("CONSUMP")
        mr = data.get("MR")
        if not mr or mr != mr:  # x != x is a NaN check.
            mr = None  # e.g. new meters report consumption without meter readings

        if not consump or consump != consump:
            if mr is None or base_reading == 0:
                continue
            consump = mr - last_reading
            last_reading = mr

        start = _hour(start)
        # Compare absolute timestamps: wall-clock times repeat at the end of DST.
        if last_start is not None and start.timestamp() <= last_start:
            continue

        _sum += consump
        row = {"start": start, "state": consump, "sum": _sum}
        if base_reading != 0 and mr is not None:
            row["sum"] = mr - base_reading
        statistics.append(row)
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
