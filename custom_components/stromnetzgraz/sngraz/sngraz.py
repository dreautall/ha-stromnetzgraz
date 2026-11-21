import asyncio
from typing import Optional
import datetime as dt
import zoneinfo
import json
import logging
import aiohttp
import jwt

API_ENDPOINT = "https://webportal.stromnetz-graz.at/api/"
# The API reads every date as Vienna wall-clock time and ignores any UTC offset.
API_TZ = zoneinfo.ZoneInfo("Europe/Vienna")
DEFAULT_TIMEOUT = 10
_LOGGER = logging.getLogger(__name__)


class StromNetzGraz:
    def __init__(
        self,
        username: str,
        password: str,
        websession: aiohttp.ClientSession,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize Stromnetz Graz API access

        :param username: The username (usually email) to access the Stromnetz Graz API with.
        :param password: The password to access the Stromnetz Graz API with.
        :param websession: The session to send requests with; it sets TLS certificates and User-Agent.
        """
        self.websession = websession
        self._timeout: int = timeout
        self._username: str = username
        self._password: str = password
        self._installations: dict[int, SNGrazInstallation] = {}
        self._jwt: Optional[str] = None

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
        return await self._query(path, payload)

    async def _query(
        self, path: str, payload: dict = [], retry: int = 2
    ) -> Optional[dict]:
        """Execute an API request and return the result as a dict loaded from the json response.

        :param path: The API Path to request.
        :param variable_values: The POST payload to send with the request.
        """

        post_args = {
            "headers": {
                aiohttp.hdrs.CONTENT_TYPE: "application/json; charset=utf-8",
            },
            "data": json.dumps(payload),
        }
        if self.ok:
            post_args["headers"][aiohttp.hdrs.AUTHORIZATION] = "Bearer " + self._jwt

        try:
            async with asyncio.timeout(self._timeout):
                resp = await self.websession.post(API_ENDPOINT + path, **post_args)
            if resp.status != 200:
                body = (await resp.text())[:300]
                raise SNGrazError(f"{path}: HTTP {resp.status} {body}", resp.status)

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
        try:
            resp = await self._query(
                "login", {"email": self._username, "password": self._password}
            )
        except SNGrazError as err:
            if err.status in (401, 403):
                raise InvalidLogin(str(err)) from err
            raise
        if "error" in resp and resp.get("error") != "":
            raise InvalidLogin(resp.get("error"))
        if ("success" in resp and not resp.get("success")) or not resp.get("token"):
            raise SNGrazError("login: no token returned", 200)

        self._jwt = resp.get("token")

        if not self.ok:
            raise SNGrazError("login: the token is already expired", 200)

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
    def get_installations(self) -> list["SNGrazInstallation"]:
        """Return list of Installations."""
        return list(self._installations.values())


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
        self._meters: dict[int, SNGrazMeter] = {}

        for _meter in info.get("meterPoints"):
            if not (meter_id := _meter.get("meterPointID")):
                continue
            self._meters[meter_id] = SNGrazMeter(meter_id, self, _meter)

    # Helper Funcs
    def get_meters(self) -> list["SNGrazMeter"]:
        """Return list of meters."""
        return list(self._meters.values())

    async def fetch_consumption_data(self, days: int = 30) -> None:
        """Fetch consumption data for meters."""
        tasks = []
        for meter in self.get_meters():
            tasks.append(meter.fetch_consumption_data(days))
        await asyncio.gather(*tasks)

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
        """Fetch the last `days` days and keep them as the meter's current data."""
        if (resp := await self.get_historic_data(days)) is not None:
            self._data = resp

    async def get_historic_data(self, days: int = 30) -> Optional[list[dict]]:
        """Get historic data.

        This data will be returned and not saved inside the SNGrazMeter instance.

        :param days: Days to get data for."""
        endTime = dt.datetime.now(dt.timezone.utc).replace(
            microsecond=0, second=0, minute=0
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
                return None
            # The API rejects (HTTP 400) a fromDate before readingsAvailableSince,
            # compared as wall-clock time to the second, so keep it as is.
            self._first_reading_date = dt.datetime.fromisoformat(
                resp.get("readingsAvailableSince")
            ).replace(tzinfo=API_TZ)

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
            endTime = endTime.astimezone(API_TZ).replace(hour=0, minute=0)
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
            "fromDate": api_time(startTime),
            "toDate": api_time(endTime),
        }

        if (resp := await self._sn_inst._sn.query("getMeterReading", payload)) is None:
            return None
        if not resp.get("readings"):
            _LOGGER.warning("No readings for meter %s from %s", self.id, payload["fromDate"])
            return None

        readings = resp.get("readings")
        result: list[dict] = []
        for reading in readings:
            res = reading_values(reading)
            if res == {}:
                continue
            # hax :( https://discuss.python.org/t/parse-z-timezone-suffix-in-datetime/2220/17
            d = reading.get("readTime")
            if d.endswith("Z"):
                d = d[:-1] + "+00:00"
            res["readTime"] = dt.datetime.fromisoformat(d)

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
        if self._first_reading is not None:
            return self._first_reading

        if (startTime := await self._get_first_reading_date()) is None:
            _LOGGER.warning("no first reading could be found")
            return None
        # Only the first week: without a meter reading there, the meter sums its consumption.
        resp = await self._fetch_data(startTime, startTime + dt.timedelta(days=7))
        self._first_reading = next((r["MR"] for r in resp or [] if "MR" in r), None)
        if self._first_reading is None:
            _LOGGER.debug("no meter reading in the first week of %s", self.id)
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


def reading_values(reading: dict) -> dict:
    """Values of one reading by type (CONSUMP, MR), taken the way the web portal does.

    The portal only reads the single-rate scale (ET) and counts every value it has,
    estimated ones included (it only marks them), so totals match the portal.
    """
    return {
        rv.get("readingType"): rv.get("value")
        for rv in reading.get("readingValues") or []
        if rv.get("scale", "ET") == "ET" and rv.get("value") is not None
    }


def api_time(time: dt.datetime) -> str:
    """Format an aware datetime as the Vienna wall-clock time the API expects."""
    return time.astimezone(API_TZ).replace(tzinfo=None).isoformat(timespec="milliseconds")


class InvalidLogin(Exception):
    """Invalid login exception."""


class SNGrazError(Exception):
    """The API answered with an HTTP error; the message includes the response body."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status
