#!/usr/bin/env python3
"""Ingest all synchronized SQM CSV files into a central SQLite database."""

import csv
import sqlite3
from pathlib import Path

BASE = Path.home() / "sqm_network"
INCOMING = BASE / "incoming"
DB = BASE / "database" / "sqm_network.sqlite"

DB.parent.mkdir(parents=True, exist_ok=True)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sqm_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utc_time TEXT NOT NULL,
    local_time TEXT,
    sensor_id TEXT NOT NULL,
    site_name TEXT,
    mag_arcsec2 REAL,
    temperature_c REAL,
    sun_alt_deg REAL,
    moon_alt_deg REAL,
    moon_phase_pct REAL,
    usable_dark_sky INTEGER,
    raw_response TEXT,
    source_file TEXT,
    UNIQUE(sensor_id, utc_time)
);
"""

INSERT = """
INSERT OR IGNORE INTO sqm_readings (
    utc_time, local_time, sensor_id, site_name, mag_arcsec2,
    temperature_c, sun_alt_deg, moon_alt_deg, moon_phase_pct,
    usable_dark_sky, raw_response, source_file
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


def to_float(value):
    if value in (None, ""):
        return None
    return float(value)


def to_int(value):
    if value in (None, ""):
        return None
    return int(value)


def ingest_file(cur, csv_file):
    scanned = 0

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            cur.execute(INSERT, (
                row.get("utc_time"),
                row.get("local_time"),
                row.get("sensor_id"),
                row.get("site_name"),
                to_float(row.get("mag_arcsec2")),
                to_float(row.get("temperature_c")),
                to_float(row.get("sun_alt_deg")),
                to_float(row.get("moon_alt_deg")),
                to_float(row.get("moon_phase_pct")),
                to_int(row.get("usable_dark_sky")),
                row.get("raw_response"),
                str(csv_file),
            ))
            scanned += 1

    return scanned


def main():
    con = sqlite3.connect(str(DB))
    cur = con.cursor()

    cur.execute(CREATE_TABLE)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sqm_time ON sqm_readings(utc_time);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sqm_local_time ON sqm_readings(local_time);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sqm_sensor ON sqm_readings(sensor_id);")

    total_files = 0
    total_rows = 0

    for csv_file in sorted(INCOMING.glob("SQM_*/*.csv")):
        rows = ingest_file(cur, csv_file)
        total_files += 1
        total_rows += rows

    con.commit()

    cur.execute("SELECT COUNT(*) FROM sqm_readings;")
    total_db = cur.fetchone()[0]

    con.close()

    print(f"Files scanned: {total_files}")
    print(f"Rows scanned:  {total_rows}")
    print(f"Rows in DB:    {total_db}")
    print(f"Database:      {DB}")


if __name__ == "__main__":
    main()
