"""Run with: uvx --with pandas --with aiohttp --with pyjwt pytest tests/"""
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

# Load the vendored client on its own: importing the integration would pull in Home Assistant.
_pkg = Path(__file__).parents[1] / "custom_components/stromnetzgraz/sngraz"
_spec = importlib.util.spec_from_file_location(
    "sngraz", _pkg / "__init__.py", submodule_search_locations=[str(_pkg)]
)
sngraz = importlib.util.module_from_spec(_spec)
sys.modules["sngraz"] = sngraz
_spec.loader.exec_module(sngraz)


def test_api_time_is_vienna_wall_clock_without_offset():
    # The API reads dates as Vienna time and ignores offsets: CET in winter, CEST in summer.
    assert sngraz.api_time(datetime(2026, 11, 20, 11, tzinfo=timezone.utc)) == "2026-11-20T12:00:00.000"
    assert sngraz.api_time(datetime(2026, 10, 20, 10, tzinfo=timezone.utc)) == "2026-10-20T12:00:00.000"


def test_api_time_keeps_seconds_of_readings_available_since():
    # fromDate must not be before readingsAvailableSince, compared to the second.
    first = datetime.fromisoformat("2026-08-31T14:30:30").replace(tzinfo=sngraz.API_TZ)
    assert sngraz.api_time(first) == "2026-08-31T14:30:30.000"


def _value(rtype, value, state="Valid", scale="ET"):
    return {"scale": scale, "readingType": rtype, "unit": "KWH", "readingState": state, "value": value}


def test_reading_values_counts_estimated_values_like_the_portal():
    reading = {"readingValues": [_value("CONSUMP", 0.1, "PartiellyEstimated"), _value("MR", 1234.5, "Estimated")]}
    assert sngraz.reading_values(reading) == {"CONSUMP": 0.1, "MR": 1234.5}


def test_reading_values_skips_missing_values_and_other_scales():
    reading = {"readingValues": [
        _value("CONSUMP", None, "NotAvailable"),
        _value("CONSUMP", 9.9, scale="HT"),
        _value("MR", 42.0),
    ]}
    assert sngraz.reading_values(reading) == {"MR": 42.0}
