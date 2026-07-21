#!/usr/bin/env python3
"""SQM-LU collector for Raspberry Pi acquisition nodes."""

import csv
import datetime as dt
import math
import os
import pathlib
import re
import time

import ephem
import serial
import yaml


def load_config():
    cfg_path = pathlib.Path(__file__).with_name("config.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_altitudes(cfg, utc_dt):
    obs = ephem.Observer()
    obs.lat = str(cfg["latitude"])
    obs.lon = str(cfg["longitude"])
    obs.elevation = cfg.get("elevation_m", 0)
    obs.date = utc_dt

    sun = ephem.Sun(obs)
    moon = ephem.Moon(obs)

    sun_alt = math.degrees(float(sun.alt))
    moon_alt = math.degrees(float(moon.alt))
    moon_phase = float(moon.phase)

    return sun_alt, moon_alt, moon_phase


def read_sqm(port, baud):
    with serial.Serial(port, baud, timeout=2) as ser:
        time.sleep(2)
        ser.write(b"rx\n")
        response = ser.readline().decode(errors="ignore").strip()

    # Example:
    # r, 21.43m,0000000021Hz,0000000000c,0000000.000s, 024.8C
    mag_match = re.search(r"r,\s*([0-9.]+)m", response)
    temp_match = re.search(r",\s*([+-]?[0-9.]+)C\s*$", response)

    if not mag_match or not temp_match:
        raise RuntimeError(f"Could not parse SQM response: {response}")

    mag = float(mag_match.group(1))
    temp_c = float(temp_match.group(1))

    return mag, temp_c, response


def append_csv(csv_file, row):
    new_file = not os.path.exists(csv_file)

    with open(csv_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if new_file:
            writer.writerow([
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
            ])

        writer.writerow(row)


def main():
    cfg = load_config()

    os.makedirs(cfg["data_dir"], exist_ok=True)
    os.makedirs(cfg["log_dir"], exist_ok=True)

    cadence = int(cfg.get("cadence_seconds", 60))

    print(f"Starting collector for {cfg['sensor_id']}", flush=True)

    while True:
        try:
            utc_now = dt.datetime.now(dt.timezone.utc)
            local_now = utc_now.astimezone()

            mag, temp_c, raw = read_sqm(cfg["serial_port"], int(cfg["baud_rate"]))
            sun_alt, moon_alt, moon_phase = compute_altitudes(cfg, utc_now)

            usable = int((sun_alt < -18.0) and (moon_alt < 0.0))

            csv_file = os.path.join(
                cfg["data_dir"],
                f"{cfg['sensor_id']}_{local_now:%Y-%m-%d}.csv"
            )

            row = [
                utc_now.isoformat(),
                local_now.isoformat(),
                cfg["sensor_id"],
                cfg["site_name"],
                mag,
                temp_c,
                round(sun_alt, 3),
                round(moon_alt, 3),
                round(moon_phase, 2),
                usable,
                raw,
            ]

            append_csv(csv_file, row)

            print(
                f"{local_now.isoformat()} "
                f"sensor={cfg['sensor_id']} "
                f"mag={mag:.2f} "
                f"temp={temp_c:.1f}C "
                f"sun={sun_alt:.1f} "
                f"moon={moon_alt:.1f} "
                f"usable={usable}",
                flush=True,
            )

        except Exception as exc:
            print(f"ERROR: {exc}", flush=True)

        time.sleep(cadence)


if __name__ == "__main__":
    main()
