"""Support for StromNetz Graz sensors."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import pandas
import numpy

import aiohttp

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ENERGY_KILO_WATT_HOUR,
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

from sngraz import SNGrazMeter, SNGrazInstallation
from .const import DOMAIN

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
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="lastMeterReading",
        name="Meter Reading",
        icon="mdi:meter-electric",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the StromNetz Graz sensor."""

    conn = hass.data[DOMAIN]

    coordinator: SNGrazDataCoordinator | None = None
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
        for meter in installation.get_meters():
            if str(meter.id) not in base_readings:
                if (base_reading := await meter.get_first_reading()) is None:
                    _LOGGER.error("could not get first reading")
                    continue
                base_readings[str(meter.id)] = base_reading

                data = {**entry.data, CONF_BASE: base_readings}
                hass.config_entries.async_update_entry(entry, data=data)

            if coordinator is None:
                coordinator = SNGrazDataCoordinator(hass, installation)
            for entity_description in SENSORS:
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
        base_readings = self.config_entry.data.get(CONF_BASE)
        if not base_readings:
            base_readings = {}

        for meter in self._installation.get_meters():
            if not meter._data:
                continue

            base_reading = 0
            if str(meter.id) in base_readings:
                base_reading = base_readings.get(str(meter.id))

            _LOGGER.info(f"adding historical statistics for {meter._short_name}")
            statistic_id = f"{DOMAIN}:energy_consumption_{meter.id}"

            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics,
                self.hass,
                1,
                statistic_id,
                True,
                {},
            )
            if not last_stats:
                # First time we insert 5 years of data (if available)
                _LOGGER.info(
                    f"first time for {meter._short_name}, trying to get up to five years"
                )
                _data = await meter.get_historic_data(5 * 365)
            else:
                # We update the statistics with the last 30 days of data to handle corrections in the data.
                _data = meter._data

            # HA statistics finest interval is hourly, so let's break it down by hour
            # Also, do some filtering afterwards, pandas otherwise creates "empty" rows
            df = pandas.DataFrame(_data)
            df_hour = (
                df.groupby(pandas.Grouper(freq="H", key="readTime"))
                .agg(
                    {
                        "CONSUMP": lambda x: numpy.nan if len(x) == 0 else sum(x),
                        "MR": lambda x: numpy.nan if len(x) == 0 else max(x),
                    }
                )
                .dropna(how="all")
            )
            df_dict = df_hour.to_dict(orient="index")

            start = list(df_dict.keys())[0].to_pydatetime() - timedelta(hours=1)
            stat = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                start,
                None,
                [statistic_id],
                "hour",
                None,
                {"sum"},
            )
            if stat:
                _sum = stat[statistic_id][0]["sum"]
                last_stats_time = stat[statistic_id][0]["start"]
            else:
                _sum = 0.0
                last_stats_time = None

            statistics = []
            last_reading = _sum
            for start, data in df_dict.items():
                if "CONSUMP" not in data or "MR" not in data:
                    continue

                consump = data["CONSUMP"]
                mr = data["MR"]
                if not mr or mr != mr:  # x != x is a NaN check.
                    continue

                if not consump or consump != consump:
                    if (
                        base_reading == 0
                    ):  # sum is too unreliable if we don't have base_reading
                        continue
                    consump = mr - last_reading
                    last_reading = mr

                # make sure minutes & (micro)seconds is 0, or HA will throw an error
                start = start.to_pydatetime().replace(minute=0, second=0, microsecond=0)
                if last_stats_time is not None and start <= last_stats_time:
                    continue

                _sum += consump
                new_stat = StatisticData(
                    start=start,
                    state=consump,
                    sum=_sum,
                )

                if base_reading != 0:
                    new_stat["sum"] = mr - base_reading

                statistics.append(new_stat)

            # metadata = StatisticMetaData(
            #    has_mean=False,
            #    has_sum=sensor.get("has_sum"),
            #    name=f"{meter._short_name} {s}",
            #    source="recorder",
            #    state_unit_of_measurement=sensor.get("unit"),
            #    statistic_id=statistic_id,
            #    unit_of_measurement=sensor.get("unit"),
            # )
            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=f"{meter._short_name} Consumption",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement=ENERGY_KILO_WATT_HOUR,
            )
            _LOGGER.info(f"adding {len(statistics)} entries to {statistic_id}")
            # async_import_statistics(self.hass, metadata, statistics)
            async_add_external_statistics(self.hass, metadata, statistics)
