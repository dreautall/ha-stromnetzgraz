"""Support for StromNetz Graz sensors."""
from __future__ import annotations

import asyncio
from datetime import timedelta, datetime
from functools import partial
import logging
import pandas

import aiohttp

from homeassistant.components.recorder import get_instance, history
from homeassistant.components.recorder.models import (
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfEnergy,
    CONF_BASE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util.unit_conversion import EnergyConverter

from sngraz import SNGrazMeter, SNGrazInstallation
from . import SNGrazConfigEntry
from .const import DOMAIN
from .cost import add_cost, price_factor
from .stats import build_cost_statistics, build_statistics, hourly_frame

_LOGGER = logging.getLogger(__name__)

ICON = "mdi:lightning-bolt-circle"
SCAN_INTERVAL = timedelta(hours=6)
MIN_TIME_BETWEEN_UPDATES = timedelta(hours=6)
PARALLEL_UPDATES = 0


SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="lastMeterConsumption",
        name="Meter Consumption",
        icon="mdi:lightning-bolt-circle",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="lastMeterReading",
        name="Meter Reading",
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SNGrazConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the StromNetz Graz sensor."""

    conn = entry.runtime_data

    entities: list[SNGrazSensor] = []

    base_readings = entry.data.get(CONF_BASE)
    if not base_readings:
        base_readings = {}

    # This fills in all installations and meters
    try:
        await conn.update_info()
    except asyncio.TimeoutError as err:
        _LOGGER.error("Timeout connecting to API: %s ", err)
        raise PlatformNotReady() from err
    except aiohttp.ClientError as err:
        _LOGGER.error("Error connecting to API: %s ", err)
        raise PlatformNotReady() from err

    for installation in conn.get_installations():
        _LOGGER.debug(f"Got installation {installation._installation_id}")
        coordinator: SNGrazDataCoordinator | None = None

        for meter in installation.get_meters():
            _LOGGER.debug(f"Got meter {meter.id}")
            # sngraz rounds readingsAvailableSince down to the hour, but the API rejects
            # (HTTP 400) any fromDate before it; round up to the next hour instead.
            if (first := await meter._get_first_reading_date()) is not None:
                meter._first_reading_date = first.replace(second=0) + timedelta(hours=1)

            if str(meter.id) not in base_readings:
                # Fails when the API sends no meter reading (MR); retried on the next setup.
                if (base_reading := await meter.get_first_reading()) is None:
                    _LOGGER.warning(
                        "could not get first reading for %s, summing consumption instead",
                        meter.id,
                    )
                else:
                    base_readings[str(meter.id)] = base_reading

                    data = {**entry.data, CONF_BASE: base_readings}
                    hass.config_entries.async_update_entry(entry, data=data)

            if coordinator is None:
                _LOGGER.debug(f"creating new coordinator")
                coordinator = SNGrazDataCoordinator(hass, installation)
            for entity_description in SENSORS:
                _LOGGER.debug(f"adding entity")
                entities.append(
                    SNGrazSensor(meter, installation, coordinator, entity_description)
                )

    async_add_entities(entities, True)


class SNGrazSensor(SensorEntity, CoordinatorEntity["SNGrazDataCoordinator"]):
    """Representation of a Stromnetz Graz sensor (= meter)."""

    def __init__(
        self,
        meter: SNGrazMeter,
        installation: SNGrazInstallation,
        coordinator: SNGrazDataCoordinator,
        entity_description: SensorEntityDescription,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator=coordinator)

        self._meter: SNGrazMeter = meter
        self._installation: SNGrazInstallation = installation

        self.entity_description = entity_description
        self._attr_unique_id = f"{self._installation.customer_id}_{self._meter.id}_{self.entity_description.key}"
        self._attr_name = f"{entity_description.name} {self._meter.id}"
        self._device_name = self._meter._short_name

    @property
    def native_value(self):
        """Return the value of the sensor."""
        return getattr(self._meter, self.entity_description.key)

    @property
    def device_info(self):
        """Return the device_info of the device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._meter.id)},
            name=self._device_name,
            manufacturer="Stromnetz Graz",
        )


class SNGrazDataCoordinator(DataUpdateCoordinator):
    """Handle Stromnetz Graz data and insert statistics."""

    def __init__(self, hass, installation: SNGrazInstallation):
        """Initialize the data handler."""
        super().__init__(
            hass,
            _LOGGER,
            name="Stromnetz Graz Sensor",
            update_interval=timedelta(hours=1),
        )
        self._installation: SNGrazInstallation = installation

    async def _async_update_data(self):
        """Update data via API."""
        await self._installation.fetch_consumption_data()
        await self._insert_statistics()

    async def _insert_statistics(self):
        """Insert statistics."""
        base_readings = self.config_entry.data.get(CONF_BASE) or {}

        for meter in self._installation.get_meters():
            if meter._data:
                await self._insert_meter_statistics(
                    meter, base_readings.get(str(meter.id), 0)
                )

    async def _last_statistic(
        self, statistic_id: str, since: datetime
    ) -> tuple[float, float | None]:
        """Sum and start (POSIX timestamp) of the newest statistic from `since` on."""
        stat = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            since,
            None,
            [statistic_id],
            "hour",
            None,
            {"sum"},
        )
        if not stat:
            return 0.0, None
        row = stat[statistic_id][0]
        start = row["start"]
        if isinstance(start, datetime):
            start = start.timestamp()
        return row["sum"], start

    async def _insert_meter_statistics(
        self, meter: SNGrazMeter, base_reading: float
    ) -> None:
        """Insert the consumption (and, with a price entity, cost) statistics of one meter."""
        _LOGGER.info("adding historical statistics for %s", meter._short_name)
        statistic_id = f"{DOMAIN}:energy_consumption_{meter.id}"

        last_stats = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            statistic_id,
            True,
            set(),
        )
        if not last_stats:
            # First time we insert 5 years of data (if available)
            _LOGGER.info(
                "first time for %s, trying to get up to five years", meter._short_name
            )
            _data = await meter.get_historic_data(5 * 365)
        else:
            # We update the statistics with the last 30 days of data to handle corrections in the data.
            _data = meter._data
        if not _data:
            return

        df = pandas.DataFrame(_data)
        # The binning to full hours will attribute readings at full hours e.g. 9:00 to the bin of 9:00-10:00
        # However the consumption actually belongs to the 8:00-9:00 bin.
        # Strictly speaking, the same applies for any binning and reading interval
        df["readTime"] = df["readTime"] - timedelta(seconds=1)
        if price_entity := self.config_entry.options.get(str(meter.id)):
            df = add_cost(
                df,
                await self._fetch_prices(
                    price_entity, df["readTime"].min(), df["readTime"].max()
                ),
            )
        df_hour = hourly_frame(df)
        if df_hour.empty:
            return

        last_sum, last_start = await self._last_statistic(
            statistic_id, df_hour.index[0].to_pydatetime() - timedelta(hours=1)
        )
        statistics = build_statistics(df_hour, base_reading, last_sum, last_start)

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{meter._short_name} Consumption",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        _LOGGER.info("adding %d entries to %s", len(statistics), statistic_id)
        async_add_external_statistics(self.hass, metadata, statistics)

        if "COST" in df_hour:
            await self._insert_cost_statistics(meter, df_hour["COST"].dropna())

    async def _fetch_prices(
        self, entity_id: str, start: pandas.Timestamp, end: pandas.Timestamp
    ) -> list[tuple[datetime, float]]:
        """Price history of entity_id in <currency>/kWh, including the price valid at start."""
        states = await get_instance(self.hass).async_add_executor_job(
            partial(
                history.state_changes_during_period,
                self.hass,
                start.to_pydatetime(),
                end.to_pydatetime(),
                entity_id,
                no_attributes=True,
                include_start_time_state=True,
            )
        )
        current = self.hass.states.get(entity_id)
        factor = price_factor(
            current.attributes.get("unit_of_measurement") if current else None
        )
        prices = []
        for state in states.get(entity_id, []):
            try:
                prices.append((state.last_changed, float(state.state) * factor))
            except ValueError:  # unknown / unavailable
                continue
        return prices

    async def _insert_cost_statistics(
        self, meter: SNGrazMeter, costs: pandas.Series
    ) -> None:
        """Insert the cost statistic; like consumption, the fetched window is re-summed each update."""
        if costs.empty:
            return
        statistic_id = f"{DOMAIN}:energy_cost_{meter.id}"

        last_sum, last_start = await self._last_statistic(
            statistic_id, costs.index[0].to_pydatetime() - timedelta(hours=1)
        )
        statistics = build_cost_statistics(costs, last_sum, last_start)

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{meter._short_name} Cost",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=None,
            unit_of_measurement=self.hass.config.currency,
        )
        _LOGGER.info("adding %d entries to %s", len(statistics), statistic_id)
        async_add_external_statistics(self.hass, metadata, statistics)
