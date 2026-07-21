#!/usr/bin/env python3
"""SQM-LU collector for LNA SQM Network acquisition nodes."""

import argparse
import csv
import datetime as dt
import io
import logging
import math
import os
import pathlib
import re
import socket
import sys
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import ephem
import serial
import yaml


LOG = logging.getLogger("sqm-collector")

CSV_HEADER = [
    "utc_time",
    "local_time",
    "sensor_id",
    "site_name",
    "mag_arcsec2",
    "temperature_c",
    "sun_alt_deg",
    "moon_alt_deg",
    "moon_phase_pct",
    "usable_dark_sky",
    "raw_response",
]

STATION_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$")


class ConfigError(RuntimeError):
    """Raised when the node configuration is missing or invalid."""


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Collect measurements from a Unihedron SQM-LU."
    )

    parser.add_argument(
        "--config",
        type=pathlib.Path,
        help=(
            "Configuration file. Defaults to SQM_NODE_CONFIG, "
            "/etc/sqm-node/config.yaml or a local config.yaml."
        ),
    )

    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate the configuration and exit without accessing the sensor.",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one acquisition cycle and exit.",
    )

    parser.add_argument(
        "--force-measurement",
        action="store_true",
        help="Ignore the solar-altitude acquisition window.",
    )

    return parser.parse_args()


def resolve_config_path(argument_path):
    candidates = []

    if argument_path is not None:
        candidates.append(argument_path)

    environment_path = os.environ.get("SQM_NODE_CONFIG")
    if environment_path:
        candidates.append(pathlib.Path(environment_path))

    script_path = pathlib.Path(__file__).resolve()

    candidates.extend([
        pathlib.Path("/etc/sqm-node/config.yaml"),
        script_path.with_name("config.yaml"),
        script_path.parent.parent / "config" / "config.yaml",
    ])

    for candidate in candidates:
        candidate = candidate.expanduser()

        if candidate.is_file():
            return candidate.resolve()

    searched = "\n  - ".join(str(path) for path in candidates)

    raise ConfigError(
        "No configuration file found. Searched:\n  - {}".format(searched)
    )


def read_yaml(path):
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
    except OSError as exc:
        raise ConfigError(
            "Could not read configuration file {}: {}".format(path, exc)
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(
            "Invalid YAML in {}: {}".format(path, exc)
        ) from exc

    if not isinstance(data, dict):
        raise ConfigError(
            "The configuration root must be a YAML mapping."
        )

    return data


def require_boolean(value, field_name):
    if not isinstance(value, bool):
        raise ConfigError(
            "{} must be true or false.".format(field_name)
        )

    return value


def normalize_config(raw):
    """Convert the new hierarchical or legacy flat YAML into one structure."""

    hierarchical = isinstance(raw.get("station"), dict)

    try:
        if hierarchical:
            station = raw["station"]
            location = raw["location"]
            sensor = raw["sensor"]
            collection = raw.get("collection", {})
            storage = raw["storage"]

            config = {
                "station_id": str(station["id"]).strip(),
                "hostname": str(
                    station.get("hostname", socket.gethostname())
                ).strip(),
                "site_name": str(station["site_name"]).strip(),
                "site_code": str(station.get("site_code", "")).strip(),

                "latitude_deg": float(location["latitude_deg"]),
                "longitude_deg": float(location["longitude_deg"]),
                "elevation_m": float(location.get("elevation_m", 0)),
                "timezone_name": str(
                    location.get("timezone", "")
                ).strip(),

                "sensor_manufacturer": str(
                    sensor.get("manufacturer", "Unihedron")
                ).strip(),
                "sensor_model": str(
                    sensor.get("model", "SQM-LU")
                ).strip(),
                "sensor_serial_number": str(
                    sensor.get("serial_number", "unknown")
                ).strip(),
                "serial_port": str(sensor["serial_port"]).strip(),
                "baud_rate": int(sensor.get("baud_rate", 115200)),

                "cadence_seconds": float(
                    collection.get("cadence_seconds", 60)
                ),
                "start_sun_altitude_deg": float(
                    collection.get("start_sun_altitude_deg", -12.0)
                ),
                "stop_sun_altitude_deg": float(
                    collection.get("stop_sun_altitude_deg", -12.0)
                ),
                "daytime_check_seconds": float(
                    collection.get("daytime_check_seconds", 300)
                ),
                "usable_sun_altitude_deg": float(
                    collection.get("usable_sun_altitude_deg", -18.0)
                ),
                "require_moon_below_horizon": require_boolean(
                    collection.get(
                        "require_moon_below_horizon",
                        True,
                    ),
                    "collection.require_moon_below_horizon",
                ),
                "serial_timeout_seconds": float(
                    collection.get("serial_timeout_seconds", 2.0)
                ),
                "serial_settle_seconds": float(
                    collection.get("serial_settle_seconds", 2.0)
                ),

                "data_dir": pathlib.Path(
                    str(storage["data_dir"])
                ).expanduser(),
                "log_dir": pathlib.Path(
                    str(storage["log_dir"])
                ).expanduser(),
                "retention_days": int(
                    storage.get("retention_days", 90)
                ),
                "fsync_each_row": require_boolean(
                    storage.get("fsync_each_row", False),
                    "storage.fsync_each_row",
                ),

                "legacy_format": False,
            }

        else:
            # Temporary compatibility with the deployed flat configuration.
            config = {
                "station_id": str(raw["sensor_id"]).strip(),
                "hostname": socket.gethostname(),
                "site_name": str(raw["site_name"]).strip(),
                "site_code": str(raw.get("site_code", "")).strip(),

                "latitude_deg": float(raw["latitude"]),
                "longitude_deg": float(raw["longitude"]),
                "elevation_m": float(raw.get("elevation_m", 0)),
                "timezone_name": str(raw.get("timezone", "")).strip(),

                "sensor_manufacturer": str(
                    raw.get("sensor_manufacturer", "Unihedron")
                ).strip(),
                "sensor_model": str(
                    raw.get("sensor_model", "SQM-LU")
                ).strip(),
                "sensor_serial_number": str(
                    raw.get("sensor_serial_number", "unknown")
                ).strip(),
                "serial_port": str(raw["serial_port"]).strip(),
                "baud_rate": int(raw.get("baud_rate", 115200)),

                "cadence_seconds": float(
                    raw.get("cadence_seconds", 60)
                ),
                "start_sun_altitude_deg": float(
                    raw.get("start_sun_altitude_deg", -12.0)
                ),
                "stop_sun_altitude_deg": float(
                    raw.get("stop_sun_altitude_deg", -12.0)
                ),
                "daytime_check_seconds": float(
                    raw.get("daytime_check_seconds", 300)
                ),
                "usable_sun_altitude_deg": float(
                    raw.get("usable_sun_altitude_deg", -18.0)
                ),
                "require_moon_below_horizon": require_boolean(
                    raw.get("require_moon_below_horizon", True),
                    "require_moon_below_horizon",
                ),
                "serial_timeout_seconds": float(
                    raw.get("serial_timeout_seconds", 2.0)
                ),
                "serial_settle_seconds": float(
                    raw.get("serial_settle_seconds", 2.0)
                ),

                "data_dir": pathlib.Path(
                    str(raw["data_dir"])
                ).expanduser(),
                "log_dir": pathlib.Path(
                    str(raw["log_dir"])
                ).expanduser(),
                "retention_days": int(
                    raw.get("retention_days", 90)
                ),
                "fsync_each_row": require_boolean(
                    raw.get("fsync_each_row", False),
                    "fsync_each_row",
                ),

                "legacy_format": True,
            }

    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(
            "Missing or invalid configuration value: {}".format(exc)
        ) from exc

    validate_config(config)
    return config


def validate_config(config):
    station_id = config["station_id"]

    if not STATION_ID_PATTERN.fullmatch(station_id):
        raise ConfigError(
            "Invalid station.id/sensor_id: {!r}".format(station_id)
        )

    if not config["site_name"]:
        raise ConfigError("station.site_name/site_name cannot be empty.")

    if not config["serial_port"]:
        raise ConfigError("sensor.serial_port/serial_port cannot be empty.")

    latitude = config["latitude_deg"]
    longitude = config["longitude_deg"]

    if not -90.0 <= latitude <= 90.0:
        raise ConfigError("Latitude must be between -90 and +90 degrees.")

    if not -180.0 <= longitude <= 180.0:
        raise ConfigError("Longitude must be between -180 and +180 degrees.")

    positive_fields = [
        "baud_rate",
        "cadence_seconds",
        "daytime_check_seconds",
        "serial_timeout_seconds",
    ]

    for field in positive_fields:
        if config[field] <= 0:
            raise ConfigError("{} must be greater than zero.".format(field))

    if config["serial_settle_seconds"] < 0:
        raise ConfigError(
            "serial_settle_seconds cannot be negative."
        )

    if (
        config["start_sun_altitude_deg"]
        > config["stop_sun_altitude_deg"]
    ):
        raise ConfigError(
            "start_sun_altitude_deg must be less than or equal to "
            "stop_sun_altitude_deg."
        )

    timezone_name = config["timezone_name"]

    if timezone_name:
        try:
            config["timezone_info"] = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(
                "Unknown timezone: {}".format(timezone_name)
            ) from exc
    else:
        config["timezone_info"] = None


def load_config(path):
    return normalize_config(read_yaml(path))


def print_config_summary(config, path):
    actual_hostname = socket.gethostname()

    print("Configuration valid")
    print("  file: {}".format(path))
    print("  station_id: {}".format(config["station_id"]))
    print("  configured_hostname: {}".format(config["hostname"]))
    print("  actual_hostname: {}".format(actual_hostname))
    print("  site_name: {}".format(config["site_name"]))
    print(
        "  sensor: {} {} serial={}".format(
            config["sensor_manufacturer"],
            config["sensor_model"],
            config["sensor_serial_number"],
        )
    )
    print("  serial_port: {}".format(config["serial_port"]))
    print(
        "  location: latitude={} longitude={} elevation_m={}".format(
            config["latitude_deg"],
            config["longitude_deg"],
            config["elevation_m"],
        )
    )
    print("  timezone: {}".format(
        config["timezone_name"] or "system local timezone"
    ))
    print(
        "  acquisition_sun_altitude: start={} stop={}".format(
            config["start_sun_altitude_deg"],
            config["stop_sun_altitude_deg"],
        )
    )
    print(
        "  usable_dark_sky: sun<{} moon_below_horizon={}".format(
            config["usable_sun_altitude_deg"],
            config["require_moon_below_horizon"],
        )
    )
    print("  data_dir: {}".format(config["data_dir"]))
    print("  legacy_format: {}".format(config["legacy_format"]))


def compute_altitudes(config, utc_datetime):
    observer = ephem.Observer()
    observer.lat = str(config["latitude_deg"])
    observer.lon = str(config["longitude_deg"])
    observer.elevation = config["elevation_m"]

    # Disable atmospheric refraction for astronomical twilight thresholds.
    observer.pressure = 0

    observer.date = (
        utc_datetime
        .astimezone(dt.timezone.utc)
        .replace(tzinfo=None)
    )

    sun = ephem.Sun(observer)
    moon = ephem.Moon(observer)

    return (
        math.degrees(float(sun.alt)),
        math.degrees(float(moon.alt)),
        float(moon.phase),
    )


def read_sqm(config):
    with serial.Serial(
        port=config["serial_port"],
        baudrate=config["baud_rate"],
        timeout=config["serial_timeout_seconds"],
    ) as serial_connection:
        time.sleep(config["serial_settle_seconds"])
        serial_connection.reset_input_buffer()
        serial_connection.write(b"rx\n")
        serial_connection.flush()

        response = (
            serial_connection
            .readline()
            .decode("ascii", errors="replace")
            .strip()
        )

    magnitude_match = re.search(
        r"r,\s*([0-9]+(?:\.[0-9]+)?)m",
        response,
    )
    temperature_match = re.search(
        r",\s*([+-]?[0-9]+(?:\.[0-9]+)?)C\s*$",
        response,
    )

    if not magnitude_match or not temperature_match:
        raise RuntimeError(
            "Could not parse SQM response: {!r}".format(response)
        )

    return (
        float(magnitude_match.group(1)),
        float(temperature_match.group(1)),
        response,
    )


def encode_csv_rows(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")

    for row in rows:
        writer.writerow(row)

    return stream.getvalue().encode("utf-8")


def write_all(file_descriptor, data):
    view = memoryview(data)

    while view:
        written = os.write(file_descriptor, view)

        if written <= 0:
            raise OSError("Could not append data to CSV file.")

        view = view[written:]


def append_csv(csv_path, row, fsync_each_row=False):
    csv_path = pathlib.Path(csv_path)

    new_file = (
        not csv_path.exists()
        or csv_path.stat().st_size == 0
    )

    rows = [CSV_HEADER, row] if new_file else [row]
    payload = encode_csv_rows(rows)

    descriptor = os.open(
        str(csv_path),
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o640,
    )

    try:
        write_all(descriptor, payload)

        if fsync_each_row:
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def local_datetime(utc_datetime, timezone_info):
    if timezone_info is None:
        return utc_datetime.astimezone()

    return utc_datetime.astimezone(timezone_info)


def should_collect(config, sun_altitude, collecting):
    if collecting:
        if sun_altitude > config["stop_sun_altitude_deg"]:
            return False
        return True

    if sun_altitude <= config["start_sun_altitude_deg"]:
        return True

    return False


def is_usable_dark_sky(config, sun_altitude, moon_altitude):
    sun_is_dark = (
        sun_altitude < config["usable_sun_altitude_deg"]
    )

    if config["require_moon_below_horizon"]:
        moon_is_acceptable = moon_altitude < 0.0
    else:
        moon_is_acceptable = True

    return int(sun_is_dark and moon_is_acceptable)


def run_collection(config, arguments):
    config["data_dir"].mkdir(parents=True, exist_ok=True)
    config["log_dir"].mkdir(parents=True, exist_ok=True)

    actual_hostname = socket.gethostname()

    if config["hostname"] and config["hostname"] != actual_hostname:
        LOG.warning(
            "hostname mismatch configured=%s actual=%s",
            config["hostname"],
            actual_hostname,
        )

    LOG.info(
        "collector started station=%s hostname=%s sensor=%s/%s "
        "serial_number=%s port=%s",
        config["station_id"],
        actual_hostname,
        config["sensor_manufacturer"],
        config["sensor_model"],
        config["sensor_serial_number"],
        config["serial_port"],
    )

    collecting = False

    while True:
        cycle_started = time.monotonic()

        try:
            utc_now = dt.datetime.now(dt.timezone.utc)
            local_now = local_datetime(
                utc_now,
                config["timezone_info"],
            )

            sun_altitude, moon_altitude, moon_phase = (
                compute_altitudes(config, utc_now)
            )

            if arguments.force_measurement:
                collecting = True
            else:
                collecting = should_collect(
                    config,
                    sun_altitude,
                    collecting,
                )

            if not collecting:
                LOG.info(
                    "waiting station=%s sun=%.2f start_threshold=%.2f",
                    config["station_id"],
                    sun_altitude,
                    config["start_sun_altitude_deg"],
                )

                if arguments.once:
                    return 0

                time.sleep(config["daytime_check_seconds"])
                continue

            magnitude, temperature_c, raw_response = read_sqm(config)

            usable_dark_sky = is_usable_dark_sky(
                config,
                sun_altitude,
                moon_altitude,
            )

            csv_path = (
                config["data_dir"]
                / "{}_{}.csv".format(
                    config["station_id"],
                    local_now.strftime("%Y-%m-%d"),
                )
            )

            row = [
                utc_now.isoformat(),
                local_now.isoformat(),
                config["station_id"],
                config["site_name"],
                magnitude,
                temperature_c,
                round(sun_altitude, 3),
                round(moon_altitude, 3),
                round(moon_phase, 2),
                usable_dark_sky,
                raw_response,
            ]

            append_csv(
                csv_path,
                row,
                fsync_each_row=config["fsync_each_row"],
            )

            LOG.info(
                "measurement station=%s mag=%.2f temp=%.1fC "
                "sun=%.2f moon=%.2f usable=%d file=%s",
                config["station_id"],
                magnitude,
                temperature_c,
                sun_altitude,
                moon_altitude,
                usable_dark_sky,
                csv_path.name,
            )

            if arguments.once:
                return 0

        except Exception:
            LOG.exception(
                "acquisition cycle failed station=%s",
                config["station_id"],
            )

            if arguments.once:
                return 1

            time.sleep(min(config["cadence_seconds"], 60.0))
            continue

        elapsed = time.monotonic() - cycle_started
        sleep_seconds = max(
            0.0,
            config["cadence_seconds"] - elapsed,
        )

        time.sleep(sleep_seconds)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    arguments = parse_arguments()

    try:
        config_path = resolve_config_path(arguments.config)
        config = load_config(config_path)

        if arguments.check_config:
            print_config_summary(config, config_path)
            return 0

        return run_collection(config, arguments)

    except ConfigError as exc:
        LOG.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        LOG.info("collector interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
