"""Run with: uvx --with pandas pytest tests/"""
import importlib.util
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas
import pytest

# Load cost.py on its own: importing the package would pull in Home Assistant.
_spec = importlib.util.spec_from_file_location(
    "cost", Path(__file__).parents[1] / "custom_components/stromnetzgraz/cost.py"
)
cost = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cost)

T0 = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("unit", "factor"),
    [
        ("EUR/kWh", 1.0),
        ("€/kWh", 1.0),
        (None, 1.0),
        ("ct/kWh", 0.01),
        ("Cent/kWh", 0.01),
        ("EUR/MWh", 0.001),
        ("ct/MWh", 0.00001),
    ],
)
def test_price_factor(unit, factor):
    assert cost.price_factor(unit) == pytest.approx(factor)


def _readings(*consumptions):
    # Like the coordinator: readTime marks the end of each quarter hour, minus 1 s.
    return pandas.DataFrame(
        {
            "readTime": [
                T0 + timedelta(minutes=15 * (i + 1), seconds=-1)
                for i in range(len(consumptions))
            ],
            "CONSUMP": list(consumptions),
        }
    )


def test_cost_uses_price_valid_at_each_reading():
    df = _readings(1.0, 2.0, 3.0, 4.0)
    prices = [(T0 - timedelta(hours=1), 0.10), (T0 + timedelta(minutes=30), 0.20)]

    out = cost.add_cost(df, prices)

    assert out["COST"].tolist() == pytest.approx([0.10, 0.20, 0.60, 0.80])


def test_readings_before_first_price_get_no_cost():
    df = _readings(1.0, 2.0)
    out = cost.add_cost(df, [(T0 + timedelta(minutes=20), 0.30)])

    assert math.isnan(out["COST"][0])
    assert out["COST"][1] == pytest.approx(0.60)


def test_no_prices_leaves_frame_untouched():
    df = _readings(1.0)
    assert "COST" not in cost.add_cost(df, [])
