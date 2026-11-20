"""Energy cost from a price entity's history. Pure pandas, no Home Assistant imports."""
from __future__ import annotations

from datetime import datetime

import pandas


def price_factor(unit: str | None) -> float:
    """Factor that turns a price in `unit` into <currency>/kWh."""
    unit = (unit or "").lower().replace(" ", "")
    factor = 0.01 if unit.startswith(("ct", "cent", "c/")) else 1.0
    return factor / 1000 if unit.endswith("/mwh") else factor


def add_cost(
    df: pandas.DataFrame, prices: list[tuple[datetime, float]]
) -> pandas.DataFrame:
    """Add a COST column: each reading's CONSUMP times the price valid at its readTime.

    `prices` are (time the price took effect, <currency>/kWh). Readings before the
    first known price get no cost.
    """
    if not prices or "CONSUMP" not in df:
        return df
    price_df = pandas.DataFrame(prices, columns=["readTime", "price"])
    price_df["readTime"] = pandas.to_datetime(price_df["readTime"], utc=True).astype(
        df["readTime"].dtype
    )
    merged = pandas.merge_asof(
        df.sort_values("readTime"),
        price_df.sort_values("readTime"),
        on="readTime",
        direction="backward",
    )
    merged["COST"] = merged["CONSUMP"] * merged["price"]
    return merged.drop(columns="price")
