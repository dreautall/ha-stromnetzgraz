import asyncio
import os
from typing import Optional
import datetime as dt
import zoneinfo
import json
import logging
import ssl
import aiohttp
import async_timeout
import jwt

from . import __version__

API_ENDPOINT = "https://webportal.stromnetz-graz.at/api/"
DEFAULT_TIMEOUT = 10
_LOGGER = logging.getLogger(__name__)


class StromNetzGraz:
    def __init__(
        self,
        username: str,
        password: str,
        timeout: int = DEFAULT_TIMEOUT,
        websession: Optional[aiohttp.ClientSession] = None,
        time_zone: Optional[dt.tzinfo] = None,
    ) -> None:
        """Initialize Stromnetz Graz API access

        :param username: The username (usually email) to access the Stromnetz Graz API with.
        :param password: The password to access the Stromnetz Graz API with.
        :param websession: The websession to use when communicating with the API.
        :param time_zone: The time zone to display times in and to use.
        """
        if websession is None:
            sslcontext = ssl.create_default_context()
            sslcontext.load_verify_locations(
                cafile=os.path.join(os.path.dirname(__file__), "certchain.crt")
            )
            conn = aiohttp.TCPConnector(ssl=sslcontext)
            self.websession = aiohttp.ClientSession(
                headers={aiohttp.hdrs.USER_AGENT: f"pySNGraz/{__version__}"},
                connector=conn,
            )
        else:
            self.websession = websession

        self._timeout: int = timeout
        self._username: str = username
        self._password: str = password
        self.time_zone: dt.tzinfo = time_zone or zoneinfo.ZoneInfo("UTC")
        self._installations: dict[int, SNGrazInstallation] = {}
        self._jwt: Optional[str] = None
        try:
            user_agent = self.websession._default_headers.get(
                aiohttp.hdrs.USER_AGENT, ""
            )  # will be fixed by aiohttp 4.0
        except Exception:  # pylint: disable=broad-except
            user_agent = ""
        self.user_agent = f"{user_agent} pySNGraz/{__version__}"

    async def close_connection(self) -> None:
        """Close the API connection.
        This method simply closes the websession used by the object."""
        await self.websession.close()

    async def query(self, path: str, payload: Optional[dict] = []) -> Optional[dict]:
        """Execute an API request and return the result.
        This call will re-authenticate if the token expired in the meantime.

        :param path: The API Path to request.
        :param variable_values: The POST payload to send with the request.
        """
        if not self.ok:
            await self.authenticate()
        if (res := await self._query(path, payload)) is None:
            return None
        return res

    async def _query(
        self, path: str, payload: dict = [], retry: int = 2
    ) -> Optional[dict]:
        """Execute an API request and return the result as a dict loaded from the json response.

        :param path: The API Path to request.
        :param variable_values: The POST payload to send with the request.
        """

        post_args = {
            "headers": {
                aiohttp.hdrs.USER_AGENT: self.user_agent,
                aiohttp.hdrs.CONTENT_TYPE: "application/json; charset=utf-8",
            },
            "data": json.dumps(payload),
        }
        if self.ok:
            post_args["headers"][aiohttp.hdrs.AUTHORIZATION] = "Bearer " + self._jwt

        try:
            async with async_timeout.timeout(self._timeout):
                resp = await self.websession.post(API_ENDPOINT + path, **post_args)
            if resp.status != 200:
                _LOGGER.error("Error connecting to API, response code %d", resp.status)
                return None

            result = await resp.json()
        except aiohttp.ClientError as err:
            if retry > 0:
                return await self._query(path, payload, retry - 1)
            _LOGGER.error("Error connecting to API: %s ", err, exc_info=True)
            raise
        except asyncio.TimeoutError:
            _LOGGER.error("Timed out when connecting to API", exc_info=True)
            raise
        # errors are only returned in flat jsons. All list jsons are valid responses.
        if isinstance(result, (dict)):
            if errors := result.get("error"):
                _LOGGER.error("Received non-compatible response %s", errors)
        return result

    @property
    def ok(self) -> bool:
        """Return True if JWT is still valid."""
        if self._jwt is None:
            return False
        try:
            jwt.decode(
                self._jwt, options={"verify_signature": False, "verify_exp": True}
            )
        except Exception:
            self._jwt = None
            return False

        return True

    # API funcs
    async def authenticate(self) -> bool:
        # Use _query to avoid authentication-loop
        if (
            resp := await self._query(
                "login", {"email": self._username, "password": self._password}
            )
        ) is None:
            return False
        if "error" in resp and resp.get("error") != "":
            raise InvalidLogin(resp.get("error"))
        if ("success" in resp and not resp.get("success")) or not resp.get("token"):
            raise ValueError("no token returned")

        self._jwt = resp.get("token")

        if not self.ok:
            raise Exception("login failed")

        return True

    async def update_info(self, *_) -> None:
        """Updates installations info."""
        if (res := await self.query("getInstallations")) is None:
            return

        for _inst in res:
            if not (installation_id := _inst.get("installationID")):
                continue
            self._installations[installation_id] = SNGrazInstallation(
                installation_id, self, _inst
            )

    # Helper Funcs
    def get_installation_ids(self) -> list[int]:
        """Return list of installation ids."""
        return list(self._installations.keys())

    def get_installations(self) -> list["SNGrazInstallation"]:
        """Return list of Installations."""
        return list(self._installations.values())

    def get_installation(self, installation_id: int) -> Optional["SNGrazInstallation"]:
        """Return an instance of SNGrazInstallation for given installation id."""
        if installation_id not in self._installations:
            raise ValueError("Could not find installation id", installation_id)
        return self._installations[installation_id]

    async def fetch_consumption_data(self, days: int = 30) -> None:
        """Fetch consumption data for installations."""
        tasks = []
        for installation in self.get_installations():
            tasks.append(installation.fetch_consumption_data(days))
        await asyncio.gather(*tasks)

    @property
    def installation_ids(self) -> list[str]:
        """Return list of installation ids."""
        return self.get_installation_ids()


class SNGrazInstallation:
    """Instance of Installation (usually an apartment/building)."""

    def __init__(self, installation_id: int, sn: StromNetzGraz, info: dict):
        """Initialize the Installation class.

        :param installation_id: The ID of the installation.
        :param sn: The StromnetzGraz instance associated with this instance of SNGrazInstallation.
        :param info: Information returned by getInstallations for installation initialization
        """
        self._sn: StromNetzGraz = sn
        self._installation_id: str = installation_id
        self._customer_id: int = info.get("customerID")
        self._customer_number: int = info.get("customerNumber")
        self._installation_number: int = info.get("installationNumber")
        self._address: str = info.get("address")
        self._meters: dict[int, SNGrazMeter] = {}

        for _meter in info.get("meterPoints"):
            if not (meter_id := _meter.get("meterPointID")):
                continue
            self._meters[meter_id] = SNGrazMeter(meter_id, self, _meter)

    # Helper Funcs
    def get_meter_ids(self) -> list[int]:
        """Return list of meter ids."""
        return list(self._meters.keys())

    def get_meters(self) -> list["SNGrazMeter"]:
        """Return list of meters."""
        return list(self._meters.values())

    def get_meter(self, meter_id: int) -> Optional["SNGrazMeter"]:
        """Return an instance of SNGrazMeter for given meter id."""
        if meter_id not in self._meters:
            raise ValueError("Could not find meter id", meter_id)
        return self._meters[meter_id]

    async def fetch_consumption_data(self, days: int = 30) -> None:
        """Fetch consumption data for meters."""
        tasks = []
        for meter in self.get_meters():
            tasks.append(meter.fetch_consumption_data(days))
        await asyncio.gather(*tasks)

    @property
    def meter_ids(self) -> list[str]:
        """Return list of meter ids."""
        return self.get_meter_ids()

    @property
    def customer_id(self) -> int:
        """Return customer id."""
        return self._customer_id


class SNGrazMeter:
    """Instance of single Meter"""

    def __init__(self, meter_id: int, sn_inst: SNGrazInstallation, info: dict):
        """Initialize the Meter class.

        :param meter_id: The ID of the meter.
        :param sn_inst: The SNGrazInstallation instance associated with this instance of SNGrazMeter
        :param info: Information returned by getInstallations for installation initialization
        """
        self._sn_inst: SNGrazInstallation = sn_inst
        self._meter_id: str = meter_id
        self._name: str = info.get("name")
        self._short_name: str = info.get("shortName")
        self._opt_state: str = info.get("optState").get("currentOptState")
        self._data: Optional[list[dict]] = None

        self._first_reading: Optional[int] = None
        self._first_reading_date: Optional[dt.datetime] = None
        self._last_consumption_date: Optional[dt.datetime] = None
        self._last_consumption: Optional[int] = None
        self._last_reading_date: Optional[dt.datetime] = None
        self._last_reading: Optional[int] = None

    async def fetch_consumption_data(self, days: int = 30) -> None:
        """Update consumption info asynchronously.

        :param days: Days to get data for."""
        endTime = dt.datetime.utcnow().replace(
            microsecond=0, second=0, minute=0, tzinfo=self._sn_inst._sn.time_zone
        )
        startTime = endTime - dt.timedelta(days=days)

        if (resp := await self._fetch_data(startTime, endTime)) is None:
            return

        self._data = resp

    async def get_historic_data(self, days: int = 30) -> Optional[list[dict]]:
        """Get historic data.

        This data will be returned and not saved inside the SNGrazMeter instance.

        :param days: Days to get data for."""
        endTime = dt.datetime.utcnow().replace(
            microsecond=0, second=0, minute=0, tzinfo=self._sn_inst._sn.time_zone
        )
        startTime = endTime - dt.timedelta(days=days)

        if (resp := await self._fetch_data(startTime, endTime)) is None:
            return None

        return resp

    async def _get_first_reading_date(self) -> Optional[dt.datetime]:
        if not self._first_reading_date:
            if (
                resp := await self._sn_inst._sn.query(
                    "getMeterReadingMetaData", {"meterPointId": self.id}
                )
            ) is None:
                _LOGGER.error("Could not get meter meta data: API query failed")
                return None
            # note: timezone missing in API reply, let's asume our timezone
            self._first_reading_date = dt.datetime.fromisoformat(
                resp.get("readingsAvailableSince")
            ).replace(tzinfo=self._sn_inst._sn.time_zone, minute=0)

        return self._first_reading_date

    async def _fetch_data(
        self, startTime: dt.datetime, endTime: dt.datetime
    ) -> Optional[list[dict]]:
        """Fetch consumption data.

        :param startTime: starting date
        :param endTime: ending date"""

        # daily data available
        if self._opt_state == "OptMiddle":
            interval = "Daily"
            endTime = endTime.replace(hour=0, minute=0)
        # 15min data available
        elif self._opt_state == "OptIn":
            interval = "QuarterHourly"
        else:
            # Most likely OptOut == no data available
            _LOGGER.warning(
                "Meter is neither OptIn (IME) nor OptMiddle (IMS), no data available"
            )
            return None

        if (first_reading := await self._get_first_reading_date()) is None:
            _LOGGER.warning("no first reading could be found")
            return None

        if startTime < first_reading:
            startTime = first_reading

        payload = {
            "unitOfConsump": "KWH",
            "interval": interval,
            "meterPointId": self.id,
            "fromDate": startTime.isoformat(timespec="milliseconds"),
            "toDate": endTime.isoformat(timespec="milliseconds"),
        }

        if (resp := await self._sn_inst._sn.query("getMeterReading", payload)) is None:
            _LOGGER.error("Could not get meter readings: API query failed")
            return None
        if not resp.get("readings"):
            _LOGGER.error("Could not get meter readings: empty reading response?")
            return None

        readings = resp.get("readings")
        result: list[dict] = []
        for reading in readings:
            res = {}
            for rv in reading.get("readingValues"):
                # Skip Estimated Values - probably wrong.
                if rv.get("readingState") != "Valid":
                    continue
                res[rv.get("readingType")] = rv.get("value")
            if res == {}:
                continue
            # hax :( https://discuss.python.org/t/parse-z-timezone-suffix-in-datetime/2220/17
            d = reading.get("readTime")
            if d.endswith("Z"):
                d = d[:-1] + "+00:00"
            res["readTime"] = dt.datetime.fromisoformat(d)
            res["readingValues"] = reading.get("readingValues")

            # Update last value trackers
            if "CONSUMP" in res and (
                not self._last_consumption_date
                or res["readTime"] > self._last_consumption_date
            ):
                self._last_consumption_date = res["readTime"]
                self._last_consumption = res["CONSUMP"]
            if "MR" in res and (
                not self._last_reading_date or res["readTime"] > self._last_reading_date
            ):
                self._last_reading_date = res["readTime"]
                self._last_reading = res["MR"]
            result.append(res)
        return result

    async def get_first_reading(self) -> Optional[int]:
        if self._first_reading:
            return self._first_reading

        if (startTime := await self._get_first_reading_date()) is None:
            _LOGGER.warning("no first reading could be found")
            return None
        endTime = startTime + dt.timedelta(days=7)

        resp = []
        while len(resp) == 0:
            if (resp := await self._fetch_data(startTime, endTime)) is None:
                _LOGGER.warning("no readings available")
                return None

            startTime += dt.timedelta(days=7)
            endTime = startTime + dt.timedelta(days=7)

        for res in resp:
            if "MR" in res:
                break
        
        if "MR" not in res:
            _LOGGER.warning("first reading does not contain a meter reading value")
            return None

        self._first_reading = res.get("MR")
        return self._first_reading

    @property
    def id(self) -> str:
        """Return meter ids."""
        return self._meter_id

    @property
    def lastMeterConsumption(self) -> Optional[int]:
        """Return the latest meter consumption value."""
        return self._last_consumption

    @property
    def lastMeterReading(self) -> Optional[int]:
        """Return the latest meter reading."""
        return self._last_reading


class InvalidLogin(Exception):
    """Invalid login exception."""
