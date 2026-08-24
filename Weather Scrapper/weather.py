"""
WeatherLogger 3.0
=================

Modern replacement for a fragile Weather Underground HTML scraper.

Features
--------
- City / postcode geocoding
- Optional country filtering
- Current weather conditions
- Temperature + apparent temperature
- Relative humidity
- Dew point
- Rain / showers / snow
- Precipitation probability
- Cloud cover
- Atmospheric pressure
- Visibility
- Wind speed / direction / gusts
- WMO weather-code interpretation
- Automatic timezone handling
- Metric / imperial units
- Automatic CSV headers
- Optional JSON output
- Retry handling
- Connection/read timeouts
- CLI arguments
- Interactive input fallback
- Continuous monitoring mode
- Proper exceptions and exit codes
- UTF-8 output
- Dataclass-based structured records

Requires:
    pip install requests

Examples:
    python weather.py Winchester --country GB

    python weather.py "Bournemouth" --country GB

    python weather.py "New York" --country US --units imperial

    python weather.py Winchester --country GB --json latest_weather.json

    python weather.py Winchester --country GB --watch 10

    python weather.py Winchester --country GB --no-csv

If no city is supplied:
    python weather.py

the program asks interactively.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

APP_NAME = "WeatherLogger"
APP_VERSION = "3.0.0"

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


# ============================================================
# WMO WEATHER INTERPRETATION CODES
# ============================================================

WMO_CODES: dict[int, str] = {
    0: "Clear sky",

    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",

    45: "Fog",
    48: "Depositing rime fog",

    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",

    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",

    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",

    66: "Light freezing rain",
    67: "Heavy freezing rain",

    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",

    77: "Snow grains",

    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",

    85: "Slight snow showers",
    86: "Heavy snow showers",

    95: "Thunderstorm",

    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


# ============================================================
# EXCEPTIONS
# ============================================================

class WeatherError(RuntimeError):
    """
    Raised when geocoding or weather retrieval fails in an
    expected/recoverable way.
    """


# ============================================================
# DATA MODELS
# ============================================================

@dataclass(slots=True)
class Location:
    query: str

    name: str
    admin1: str
    country: str
    country_code: str

    latitude: float
    longitude: float

    timezone: str

    elevation_m: float | None

    @property
    def display_name(self) -> str:
        """
        Produce a human-friendly geographic name.
        """

        parts = [
            self.name,
            self.admin1,
            self.country,
        ]

        return ", ".join(
            item
            for item in parts
            if item
        )


@dataclass(slots=True)
class WeatherRecord:
    # Logging information
    recorded_at: str
    source_time: str

    # Location
    query: str
    location: str
    country_code: str

    latitude: float
    longitude: float

    timezone: str
    elevation_m: float | None

    # General condition
    weather_code: int
    condition: str

    # Temperature
    temperature: float | None
    apparent_temperature: float | None
    temperature_unit: str

    # Moisture
    humidity_percent: float | None
    dew_point: float | None

    # Precipitation
    precipitation: float | None
    rain: float | None
    showers: float | None
    snowfall: float | None

    precipitation_unit: str
    precipitation_probability_percent: float | None

    # Atmosphere
    cloud_cover_percent: float | None

    pressure_msl_hpa: float | None
    surface_pressure_hpa: float | None

    visibility_m: float | None

    # Wind
    wind_speed: float | None
    wind_gusts: float | None
    wind_speed_unit: str

    wind_direction_degrees: float | None
    wind_direction_cardinal: str

    # Solar/day state
    is_day: bool | None


# ============================================================
# HTTP SESSION
# ============================================================

def build_session() -> requests.Session:
    """
    Build a reusable Requests session with automatic retries.

    Retries are useful for temporary failures such as:
        HTTP 429
        HTTP 500
        HTTP 502
        HTTP 503
        HTTP 504
    """

    retry_strategy = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,

        backoff_factor=0.6,

        status_forcelist=(
            429,
            500,
            502,
            503,
            504,
        ),

        allowed_methods=frozenset({
            "GET",
        }),

        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy
    )

    session = requests.Session()

    session.headers.update({
        "User-Agent":
            f"{APP_NAME}/{APP_VERSION}",

        "Accept":
            "application/json",
    })

    session.mount(
        "https://",
        adapter,
    )

    session.mount(
        "http://",
        adapter,
    )

    return session


# ============================================================
# GENERIC JSON REQUEST
# ============================================================

def request_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    timeout: tuple[float, float] = (5.0, 15.0),
) -> dict[str, Any]:

    try:

        response = session.get(
            url,
            params=params,
            timeout=timeout,
        )

        response.raise_for_status()

    except requests.Timeout as exc:

        raise WeatherError(
            f"Request timed out while contacting {url}"
        ) from exc

    except requests.HTTPError as exc:

        detail = ""

        try:

            error_payload = response.json()

            detail = (
                error_payload.get("reason")
                or error_payload.get("error")
                or ""
            )

        except Exception:
            pass

        extra = (
            f" — {detail}"
            if detail
            else ""
        )

        raise WeatherError(
            f"Weather server returned HTTP "
            f"{response.status_code}{extra}"
        ) from exc

    except requests.RequestException as exc:

        raise WeatherError(
            f"Network error: {exc}"
        ) from exc

    try:

        payload = response.json()

    except ValueError as exc:

        raise WeatherError(
            "The weather service returned invalid JSON."
        ) from exc

    if not isinstance(payload, dict):

        raise WeatherError(
            "Unexpected response format from weather service."
        )

    if payload.get("error"):

        raise WeatherError(
            str(
                payload.get(
                    "reason",
                    "Unknown weather API error"
                )
            )
        )

    return payload


# ============================================================
# GEOCODING
# ============================================================

def geocode_city(
    session: requests.Session,
    query: str,
    country_code: str | None = None,
) -> Location:

    params: dict[str, Any] = {
        "name": query.strip(),
        "count": 10,
        "language": "en",
        "format": "json",
    }

    if country_code:

        params["countryCode"] = (
            country_code
            .strip()
            .upper()
        )

    data = request_json(
        session,
        GEOCODING_URL,
        params,
    )

    results = data.get("results") or []

    if not results:

        country_message = (
            f" in {country_code.upper()}"
            if country_code
            else ""
        )

        raise WeatherError(
            f"No location found for "
            f"{query!r}{country_message}."
        )

    best = results[0]

    try:

        latitude = float(
            best["latitude"]
        )

        longitude = float(
            best["longitude"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:

        raise WeatherError(
            "Geocoding result did not contain valid coordinates."
        ) from exc

    elevation = best.get(
        "elevation"
    )

    if elevation is not None:

        try:
            elevation = float(elevation)

        except (
            TypeError,
            ValueError,
        ):
            elevation = None

    return Location(
        query=query,

        name=str(
            best.get(
                "name",
                query,
            )
        ),

        admin1=str(
            best.get(
                "admin1",
                "",
            )
            or ""
        ),

        country=str(
            best.get(
                "country",
                "",
            )
            or ""
        ),

        country_code=str(
            best.get(
                "country_code",
                "",
            )
            or ""
        ),

        latitude=latitude,
        longitude=longitude,

        timezone=str(
            best.get(
                "timezone",
                "auto",
            )
        ),

        elevation_m=elevation,
    )


# ============================================================
# WIND DIRECTION
# ============================================================

def wind_cardinal(
    degrees: float | None,
) -> str:

    if degrees is None:
        return ""

    compass = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )

    index = int(
        (degrees + 11.25)
        // 22.5
    ) % 16

    return compass[index]


# ============================================================
# HOURLY VALUE MATCHING
# ============================================================

def nearest_hourly_value(
    hourly: dict[str, Any],
    variable: str,
    source_time: str,
) -> float | None:
    """
    Extract the hourly value corresponding to the current
    weather observation hour.

    Current observations can occur between whole forecast
    hours, so:
        05:15

    is matched with:
        05:00
    """

    times = hourly.get("time")
    values = hourly.get(variable)

    if not isinstance(times, list):
        return None

    if not isinstance(values, list):
        return None

    if not times:
        return None

    # YYYY-MM-DDTHH
    source_hour = source_time[:13]

    index = None

    for i, timestamp in enumerate(times):

        if str(timestamp).startswith(
            source_hour
        ):

            index = i
            break

    # Fallback
    if index is None:
        return None

    if index >= len(values):
        return None

    value = values[index]

    if value is None:
        return None

    try:
        return float(value)

    except (
        ValueError,
        TypeError,
    ):
        return None


# ============================================================
# DOWNLOAD WEATHER
# ============================================================

def fetch_weather(
    session: requests.Session,
    location: Location,
    units: str,
) -> WeatherRecord:

    imperial = (
        units == "imperial"
    )

    current_variables = (
        "temperature_2m",
        "relative_humidity_2m",
        "apparent_temperature",
        "is_day",
        "precipitation",
        "rain",
        "showers",
        "snowfall",
        "weather_code",
        "cloud_cover",
        "pressure_msl",
        "surface_pressure",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
    )

    hourly_variables = (
        "precipitation_probability",
        "dew_point_2m",
        "visibility",
    )

    params: dict[str, Any] = {

        "latitude":
            location.latitude,

        "longitude":
            location.longitude,

        # Automatically select location timezone
        "timezone":
            "auto",

        # We only need today for current logging.
        "forecast_days":
            1,

        "current":
            ",".join(
                current_variables
            ),

        "hourly":
            ",".join(
                hourly_variables
            ),

        "temperature_unit":
            (
                "fahrenheit"
                if imperial
                else "celsius"
            ),

        "wind_speed_unit":
            (
                "mph"
                if imperial
                else "kmh"
            ),

        "precipitation_unit":
            (
                "inch"
                if imperial
                else "mm"
            ),
    }

    data = request_json(
        session,
        FORECAST_URL,
        params,
    )

    current = data.get(
        "current"
    )

    if not isinstance(
        current,
        dict,
    ):

        raise WeatherError(
            "Weather API response did not contain "
            "current-weather data."
        )

    current_units = (
        data.get("current_units")
        or {}
    )

    hourly = (
        data.get("hourly")
        or {}
    )

    source_time = str(
        current.get("time")
        or ""
    )

    # --------------------------------------------------------
    # SAFE NUMERIC EXTRACTION
    # --------------------------------------------------------

    def number(
        key: str,
    ) -> float | None:

        value = current.get(
            key
        )

        if value is None:
            return None

        try:
            return float(value)

        except (
            TypeError,
            ValueError,
        ):
            return None

    # --------------------------------------------------------
    # WEATHER CODE
    # --------------------------------------------------------

    raw_weather_code = current.get(
        "weather_code"
    )

    try:
        weather_code = int(
            raw_weather_code
        )

    except (
        TypeError,
        ValueError,
    ):
        weather_code = -1

    condition = WMO_CODES.get(
        weather_code,
        f"Unknown WMO weather code {weather_code}",
    )

    # --------------------------------------------------------
    # WIND
    # --------------------------------------------------------

    wind_direction = number(
        "wind_direction_10m"
    )

    cardinal_direction = wind_cardinal(
        wind_direction
    )

    # --------------------------------------------------------
    # DAY/NIGHT
    # --------------------------------------------------------

    raw_is_day = current.get(
        "is_day"
    )

    if raw_is_day is None:

        is_day = None

    else:

        try:
            is_day = bool(
                int(raw_is_day)
            )

        except (
            TypeError,
            ValueError,
        ):
            is_day = None

    # --------------------------------------------------------
    # CREATE NORMALISED RECORD
    # --------------------------------------------------------

    return WeatherRecord(

        recorded_at=(
            datetime
            .now()
            .astimezone()
            .isoformat(
                timespec="seconds"
            )
        ),

        source_time=source_time,

        query=location.query,

        location=(
            location.display_name
        ),

        country_code=(
            location.country_code
        ),

        latitude=(
            location.latitude
        ),

        longitude=(
            location.longitude
        ),

        timezone=str(
            data.get(
                "timezone",
                location.timezone,
            )
        ),

        elevation_m=(
            location.elevation_m
        ),

        weather_code=(
            weather_code
        ),

        condition=(
            condition
        ),

        temperature=number(
            "temperature_2m"
        ),

        apparent_temperature=number(
            "apparent_temperature"
        ),

        temperature_unit=str(
            current_units.get(
                "temperature_2m",
                "",
            )
        ),

        humidity_percent=number(
            "relative_humidity_2m"
        ),

        dew_point=nearest_hourly_value(
            hourly,
            "dew_point_2m",
            source_time,
        ),

        precipitation=number(
            "precipitation"
        ),

        rain=number(
            "rain"
        ),

        showers=number(
            "showers"
        ),

        snowfall=number(
            "snowfall"
        ),

        precipitation_unit=str(
            current_units.get(
                "precipitation",
                "",
            )
        ),

        precipitation_probability_percent=(
            nearest_hourly_value(
                hourly,
                "precipitation_probability",
                source_time,
            )
        ),

        cloud_cover_percent=number(
            "cloud_cover"
        ),

        pressure_msl_hpa=number(
            "pressure_msl"
        ),

        surface_pressure_hpa=number(
            "surface_pressure"
        ),

        visibility_m=nearest_hourly_value(
            hourly,
            "visibility",
            source_time,
        ),

        wind_speed=number(
            "wind_speed_10m"
        ),

        wind_gusts=number(
            "wind_gusts_10m"
        ),

        wind_speed_unit=str(
            current_units.get(
                "wind_speed_10m",
                "",
            )
        ),

        wind_direction_degrees=(
            wind_direction
        ),

        wind_direction_cardinal=(
            cardinal_direction
        ),

        is_day=is_day,
    )


# ============================================================
# CSV STORAGE
# ============================================================

def append_csv(
    record: WeatherRecord,
    path: Path,
) -> None:
    """
    Append one weather record.

    Automatically creates:
        - directories
        - CSV file
        - CSV header
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        field.name
        for field
        in fields(WeatherRecord)
    ]

    needs_header = (
        not path.exists()
        or path.stat().st_size == 0
    )

    with path.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )

        if needs_header:
            writer.writeheader()

        writer.writerow(
            asdict(record)
        )


# ============================================================
# JSON STORAGE
# ============================================================

def write_json(
    record: WeatherRecord,
    path: Path,
) -> None:
    """
    Store the newest observation as pretty JSON.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = json.dumps(
        asdict(record),
        indent=4,
        ensure_ascii=False,
    )

    path.write_text(
        data,
        encoding="utf-8",
    )


# ============================================================
# DISPLAY FORMATTING
# ============================================================

def format_value(
    value: Any,
    unit: str = "",
    fallback: str = "n/a",
) -> str:

    if value is None:
        return fallback

    if value == "":
        return fallback

    if isinstance(
        value,
        float,
    ):

        value = f"{value:.1f}"

    return f"{value}{unit}"


# ============================================================
# TERMINAL REPORT
# ============================================================

def print_report(
    record: WeatherRecord,
) -> None:

    if record.is_day is True:
        day_state = "Day"

    elif record.is_day is False:
        day_state = "Night"

    else:
        day_state = "Unknown"

    title = record.location

    divider = "=" * max(
        30,
        len(title),
    )

    print()
    print(title)
    print(divider)

    print(
        f"Condition       : "
        f"{record.condition}"
    )

    print(
        f"Temperature     : "
        f"{format_value(record.temperature, record.temperature_unit)}"
    )

    print(
        f"Feels like      : "
        f"{format_value(record.apparent_temperature, record.temperature_unit)}"
    )

    print(
        f"Humidity        : "
        f"{format_value(record.humidity_percent, '%')}"
    )

    print(
        f"Dew point       : "
        f"{format_value(record.dew_point, record.temperature_unit)}"
    )

    print(
        f"Precipitation   : "
        f"{format_value(record.precipitation, record.precipitation_unit)}"
    )

    print(
        f"Rain            : "
        f"{format_value(record.rain, record.precipitation_unit)}"
    )

    print(
        f"Showers         : "
        f"{format_value(record.showers, record.precipitation_unit)}"
    )

    print(
        f"Snowfall        : "
        f"{format_value(record.snowfall)}"
    )

    print(
        f"Precip chance   : "
        f"{format_value(record.precipitation_probability_percent, '%')}"
    )

    print(
        f"Cloud cover     : "
        f"{format_value(record.cloud_cover_percent, '%')}"
    )

    print(
        f"Pressure MSL    : "
        f"{format_value(record.pressure_msl_hpa, ' hPa')}"
    )

    print(
        f"Surface pressure: "
        f"{format_value(record.surface_pressure_hpa, ' hPa')}"
    )

    print(
        f"Visibility      : "
        f"{format_value(record.visibility_m, ' m')}"
    )

    wind_text = format_value(
        record.wind_speed,
        f" {record.wind_speed_unit}",
    )

    if record.wind_direction_cardinal:

        wind_text += (
            f" {record.wind_direction_cardinal}"
        )

    if record.wind_direction_degrees is not None:

        wind_text += (
            f" "
            f"({record.wind_direction_degrees:.0f}°)"
        )

    print(
        f"Wind            : "
        f"{wind_text}"
    )

    print(
        f"Wind gusts      : "
        f"{format_value(record.wind_gusts, ' ' + record.wind_speed_unit)}"
    )

    print(
        f"Day / night     : "
        f"{day_state}"
    )

    print(
        f"Weather time    : "
        f"{record.source_time}"
    )

    print(
        f"Timezone        : "
        f"{record.timezone}"
    )

    print(
        f"Logged at       : "
        f"{record.recorded_at}"
    )

    print(
        f"Coordinates     : "
        f"{record.latitude:.5f}, "
        f"{record.longitude:.5f}"
    )

    if record.elevation_m is not None:

        print(
            f"Elevation       : "
            f"{record.elevation_m:.1f} m"
        )


# ============================================================
# ARGUMENT PARSER
# ============================================================

def parse_arguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(

        prog="weather.py",

        description=(
            "Advanced city weather logger "
            "using the Open-Meteo weather API."
        ),
    )

    parser.add_argument(
        "city",
        nargs="?",
        help=(
            'City, postcode or location. '
            'Example: "Winchester"'
        ),
    )

    parser.add_argument(
        "--country",
        type=str,
        help=(
            "ISO 3166-1 alpha-2 country code. "
            "Examples: GB, US, FR, DE."
        ),
    )

    parser.add_argument(
        "--units",
        choices=(
            "metric",
            "imperial",
        ),

        default="metric",

        help=(
            "Measurement system. "
            "Default: metric"
        ),
    )

    parser.add_argument(
        "--csv",

        type=Path,

        default=Path(
            "weather.csv"
        ),

        help=(
            "CSV output location. "
            "Default: weather.csv"
        ),
    )

    parser.add_argument(
        "--json",

        dest="json_path",

        type=Path,

        help=(
            "Optionally write the newest "
            "observation to a JSON file."
        ),
    )

    parser.add_argument(
        "--watch",

        type=float,

        metavar="MINUTES",

        help=(
            "Continuously fetch weather every "
            "specified number of minutes."
        ),
    )

    parser.add_argument(
        "--no-csv",

        action="store_true",

        help=(
            "Do not save observations to CSV."
        ),
    )

    parser.add_argument(
        "--quiet",

        action="store_true",

        help=(
            "Suppress human-readable terminal output."
        ),
    )

    parser.add_argument(
        "--debug",

        action="store_true",

        help=(
            "Enable diagnostic logging."
        ),
    )

    parser.add_argument(
        "--version",

        action="version",

        version=(
            f"%(prog)s {APP_VERSION}"
        ),
    )

    args = parser.parse_args()

    if args.watch is not None:

        if args.watch < 1:

            parser.error(
                "--watch must be at least 1 minute."
            )

    if args.country:

        args.country = (
            args.country
            .strip()
            .upper()
        )

        if len(args.country) != 2:

            parser.error(
                "--country must be a two-letter "
                "ISO country code such as GB."
            )

    return args


# ============================================================
# SINGLE UPDATE
# ============================================================

def run_once(
    session: requests.Session,
    location: Location,
    args: argparse.Namespace,
) -> WeatherRecord:

    record = fetch_weather(
        session,
        location,
        args.units,
    )

    if not args.quiet:

        print_report(
            record
        )

    if not args.no_csv:

        append_csv(
            record,
            args.csv,
        )

        if not args.quiet:

            print(
                f"CSV appended     : "
                f"{args.csv.resolve()}"
            )

    if args.json_path:

        write_json(
            record,
            args.json_path,
        )

        if not args.quiet:

            print(
                f"JSON updated     : "
                f"{args.json_path.resolve()}"
            )

    return record


# ============================================================
# MAIN APPLICATION
# ============================================================

def main() -> int:

    args = parse_arguments()

    logging.basicConfig(

        level=(
            logging.DEBUG
            if args.debug
            else logging.WARNING
        ),

        format=(
            "%(asctime)s "
            "[%(levelname)s] "
            "%(message)s"
        ),

        datefmt="%H:%M:%S",
    )

    # --------------------------------------------------------
    # INTERACTIVE FALLBACK
    # --------------------------------------------------------

    if args.city:

        city = (
            args.city.strip()
        )

    else:

        try:

            city = input(
                "Enter city, postcode or location: "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt,
        ):

            print()

            return 130

    if not city:

        print(
            "Error: a city/location is required.",
            file=sys.stderr,
        )

        return 2

    # --------------------------------------------------------
    # BUILD CONNECTION SESSION
    # --------------------------------------------------------

    session = build_session()

    try:

        # ----------------------------------------------------
        # GEOCODE ONCE
        # ----------------------------------------------------

        location = geocode_city(
            session,
            city,
            args.country,
        )

        if not args.quiet:

            print(
                f"Resolved location : "
                f"{location.display_name}"
            )

            print(
                f"Coordinates       : "
                f"{location.latitude:.5f}, "
                f"{location.longitude:.5f}"
            )

        # ----------------------------------------------------
        # ONE-SHOT MODE
        # ----------------------------------------------------

        if args.watch is None:

            run_once(
                session,
                location,
                args,
            )

            return 0

        # ----------------------------------------------------
        # CONTINUOUS LOGGER MODE
        # ----------------------------------------------------

        interval_seconds = (
            args.watch * 60
        )

        if not args.quiet:

            print()

            print(
                f"Continuous mode: updating every "
                f"{args.watch:g} minute(s)."
            )

            print(
                "Press Ctrl+C to stop."
            )

        while True:

            cycle_start = (
                time.monotonic()
            )

            try:

                run_once(
                    session,
                    location,
                    args,
                )

            except WeatherError as exc:

                logging.error(
                    "%s",
                    exc,
                )

            # Calculate how long the request itself took.
            elapsed = (
                time.monotonic()
                - cycle_start
            )

            sleep_duration = max(
                0.0,
                interval_seconds - elapsed,
            )

            time.sleep(
                sleep_duration
            )

    except KeyboardInterrupt:

        print(
            "\nWeather logger stopped."
        )

        return 130

    except WeatherError as exc:

        print(
            f"Weather error: {exc}",
            file=sys.stderr,
        )

        return 1

    finally:

        session.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    raise SystemExit(
        main()
    )
