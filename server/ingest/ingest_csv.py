#!/usr/bin/env python3
"""Resilient ingestion of synchronized SQM CSV files into SQLite."""

import argparse
import csv
import datetime as dt
import logging
import pathlib
import sqlite3
import sys


LOG = logging.getLogger("sqm-ingest")

EXPECTED_COLUMNS = [
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

CREATE_READINGS_TABLE = """
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

CREATE_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS sqm_ingest_files (
    source_file TEXT PRIMARY KEY,
    file_size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    status TEXT NOT NULL,
    rows_seen INTEGER NOT NULL DEFAULT 0,
    rows_inserted INTEGER NOT NULL DEFAULT 0,
    rows_rejected INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    processed_at TEXT NOT NULL
);
"""

CREATE_ERRORS_TABLE = """
CREATE TABLE IF NOT EXISTS sqm_ingest_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    error TEXT NOT NULL,
    raw_line TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(
        source_file,
        file_size,
        mtime_ns,
        line_number,
        error
    )
);
"""

INSERT_READING = """
INSERT OR IGNORE INTO sqm_readings (
    utc_time,
    local_time,
    sensor_id,
    site_name,
    mag_arcsec2,
    temperature_c,
    sun_alt_deg,
    moon_alt_deg,
    moon_phase_pct,
    usable_dark_sky,
    raw_response,
    source_file
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

REPLACE_FILE_STATE = """
INSERT OR REPLACE INTO sqm_ingest_files (
    source_file,
    file_size,
    mtime_ns,
    status,
    rows_seen,
    rows_inserted,
    rows_rejected,
    last_error,
    processed_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

INSERT_ERROR = """
INSERT OR IGNORE INTO sqm_ingest_errors (
    source_file,
    file_size,
    mtime_ns,
    line_number,
    error,
    raw_line,
    created_at
)
VALUES (?, ?, ?, ?, ?, ?, ?);
"""


class FileFormatError(RuntimeError):
    """Raised when a CSV file cannot be interpreted safely."""


class RowFormatError(RuntimeError):
    """Raised when one CSV row is invalid."""


class FileChangedError(RuntimeError):
    """Raised when a file changes while its snapshot is being read."""


def parse_arguments():
    default_base = pathlib.Path.home() / "sqm_network"

    parser = argparse.ArgumentParser(
        description="Ingest synchronized SQM CSV files into SQLite."
    )

    parser.add_argument(
        "--base-dir",
        type=pathlib.Path,
        default=default_base,
        help="Operational server directory.",
    )

    parser.add_argument(
        "--incoming-dir",
        type=pathlib.Path,
        help="Override the incoming CSV directory.",
    )

    parser.add_argument(
        "--database",
        type=pathlib.Path,
        help="Override the SQLite database path.",
    )

    parser.add_argument(
        "--quarantine-dir",
        type=pathlib.Path,
        help="Override the quarantine directory.",
    )

    parser.add_argument(
        "--pattern",
        default="SQM_*/*.csv",
        help="Glob pattern relative to the incoming directory.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess files even when size and modification time match.",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero when any file or row is rejected.",
    )

    return parser.parse_args()


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def modification_time_ns(stat_result):
    value = getattr(stat_result, "st_mtime_ns", None)

    if value is not None:
        return int(value)

    return int(stat_result.st_mtime * 1000000000)


def empty_to_none(value):
    if value in (None, ""):
        return None

    return value


def to_float(value, field_name):
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        raise RowFormatError(
            "{} is not a valid number: {!r}".format(
                field_name,
                value,
            )
        )


def to_int(value, field_name):
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        raise RowFormatError(
            "{} is not a valid integer: {!r}".format(
                field_name,
                value,
            )
        )


def parse_single_csv_line(raw_line, line_number):
    if b"\x00" in raw_line:
        raise RowFormatError(
            "line contains one or more NUL bytes"
        )

    try:
        text = raw_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RowFormatError(
            "invalid UTF-8 at byte {}".format(exc.start)
        )

    try:
        values = next(csv.reader([text], strict=True))
    except csv.Error as exc:
        raise RowFormatError(
            "CSV parsing error: {}".format(exc)
        )

    if len(values) != len(EXPECTED_COLUMNS):
        raise RowFormatError(
            "expected {} columns, found {}".format(
                len(EXPECTED_COLUMNS),
                len(values),
            )
        )

    return values


def parse_header(raw_header):
    if b"\x00" in raw_header:
        raise FileFormatError("CSV header contains NUL bytes.")

    try:
        text = raw_header.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileFormatError(
            "CSV header is not valid UTF-8: {}".format(exc)
        )

    try:
        header = next(csv.reader([text], strict=True))
    except csv.Error as exc:
        raise FileFormatError(
            "Could not parse CSV header: {}".format(exc)
        )

    if header != EXPECTED_COLUMNS:
        raise FileFormatError(
            "Unexpected CSV header. Expected {!r}, found {!r}".format(
                EXPECTED_COLUMNS,
                header,
            )
        )

    return header


def convert_row(values, csv_file):
    row = dict(zip(EXPECTED_COLUMNS, values))

    utc_time = row["utc_time"].strip()
    sensor_id = row["sensor_id"].strip()

    if not utc_time:
        raise RowFormatError("utc_time cannot be empty")

    if not sensor_id:
        raise RowFormatError("sensor_id cannot be empty")

    expected_station = csv_file.parent.name

    if (
        expected_station.startswith("SQM_")
        and sensor_id != expected_station
    ):
        raise RowFormatError(
            "sensor_id {!r} does not match directory {!r}".format(
                sensor_id,
                expected_station,
            )
        )

    usable_dark_sky = to_int(
        row.get("usable_dark_sky"),
        "usable_dark_sky",
    )

    if usable_dark_sky not in (None, 0, 1):
        raise RowFormatError(
            "usable_dark_sky must be 0 or 1"
        )

    return (
        utc_time,
        empty_to_none(row.get("local_time")),
        sensor_id,
        empty_to_none(row.get("site_name")),
        to_float(row.get("mag_arcsec2"), "mag_arcsec2"),
        to_float(row.get("temperature_c"), "temperature_c"),
        to_float(row.get("sun_alt_deg"), "sun_alt_deg"),
        to_float(row.get("moon_alt_deg"), "moon_alt_deg"),
        to_float(row.get("moon_phase_pct"), "moon_phase_pct"),
        usable_dark_sky,
        empty_to_none(row.get("raw_response")),
        str(csv_file.resolve()),
    )


def raw_line_excerpt(raw_line):
    excerpt = raw_line[:500]
    return repr(excerpt)


def read_stable_snapshot(csv_file):
    stat_before = csv_file.stat()
    data = csv_file.read_bytes()
    stat_after = csv_file.stat()

    before_mtime = modification_time_ns(stat_before)
    after_mtime = modification_time_ns(stat_after)

    if (
        stat_before.st_size != stat_after.st_size
        or before_mtime != after_mtime
    ):
        raise FileChangedError(
            "file changed while being read"
        )

    if len(data) != stat_after.st_size:
        raise FileChangedError(
            "snapshot size differs from current file size"
        )

    return (
        data,
        int(stat_after.st_size),
        after_mtime,
    )


def initialize_database(connection):
    cursor = connection.cursor()

    cursor.execute(CREATE_READINGS_TABLE)
    cursor.execute(CREATE_FILES_TABLE)
    cursor.execute(CREATE_ERRORS_TABLE)

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_sqm_time ON sqm_readings(utc_time);"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_sqm_local_time ON sqm_readings(local_time);"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_sqm_sensor ON sqm_readings(sensor_id);"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_ingest_errors_file "
        "ON sqm_ingest_errors(source_file);"
    )

    connection.commit()


def unchanged_file(
    connection,
    source_file,
    file_size,
    mtime_ns,
):
    row = connection.execute(
        """
        SELECT file_size, mtime_ns, status
        FROM sqm_ingest_files
        WHERE source_file = ?;
        """,
        (source_file,),
    ).fetchone()

    if row is None:
        return False

    previous_size, previous_mtime, previous_status = row

    return (
        int(previous_size) == int(file_size)
        and int(previous_mtime) == int(mtime_ns)
        and previous_status in ("ok", "warning", "error")
    )


def record_error(
    connection,
    source_file,
    file_size,
    mtime_ns,
    line_number,
    error,
    raw_line,
):
    connection.execute(
        INSERT_ERROR,
        (
            source_file,
            file_size,
            mtime_ns,
            line_number,
            str(error),
            raw_line_excerpt(raw_line),
            utc_now(),
        ),
    )


def update_file_state(
    connection,
    source_file,
    file_size,
    mtime_ns,
    status,
    rows_seen,
    rows_inserted,
    rows_rejected,
    last_error,
):
    connection.execute(
        REPLACE_FILE_STATE,
        (
            source_file,
            file_size,
            mtime_ns,
            status,
            rows_seen,
            rows_inserted,
            rows_rejected,
            last_error,
            utc_now(),
        ),
    )


def quarantine_file(
    csv_file,
    quarantine_directory,
    snapshot_data,
    file_size,
    mtime_ns,
):
    """Store the exact byte snapshot that produced the ingest error."""

    station_directory = (
        quarantine_directory
        / csv_file.parent.name
    )
    station_directory.mkdir(parents=True, exist_ok=True)

    destination = station_directory / (
        "{}.size{}.mtime{}.corrupt".format(
            csv_file.name,
            file_size,
            mtime_ns,
        )
    )

    if not destination.exists():
        temporary = destination.with_name(
            destination.name + ".tmp"
        )

        temporary.write_bytes(snapshot_data)
        temporary.replace(destination)

    return destination


def ingest_snapshot(
    connection,
    csv_file,
    data,
    file_size,
    mtime_ns,
):
    source_file = str(csv_file.resolve())
    physical_lines = data.splitlines()

    if not physical_lines:
        raise FileFormatError("CSV file is empty.")

    parse_header(physical_lines[0])

    rows_seen = 0
    rows_inserted = 0
    rows_rejected = 0
    errors = []

    cursor = connection.cursor()
    cursor.execute("SAVEPOINT ingest_one_file")

    try:
        for line_number, raw_line in enumerate(
            physical_lines[1:],
            start=2,
        ):
            if not raw_line.strip():
                continue

            rows_seen += 1

            try:
                values = parse_single_csv_line(
                    raw_line,
                    line_number,
                )
                converted = convert_row(values, csv_file)

                cursor.execute(INSERT_READING, converted)

                if cursor.rowcount > 0:
                    rows_inserted += 1

            except RowFormatError as exc:
                rows_rejected += 1
                errors.append((
                    line_number,
                    str(exc),
                    raw_line,
                ))

        cursor.execute("RELEASE ingest_one_file")

    except Exception:
        cursor.execute("ROLLBACK TO ingest_one_file")
        cursor.execute("RELEASE ingest_one_file")
        raise

    status = "warning" if errors else "ok"
    last_error = errors[-1][1] if errors else None

    for line_number, error, raw_line in errors:
        record_error(
            connection,
            source_file,
            file_size,
            mtime_ns,
            line_number,
            error,
            raw_line,
        )

    update_file_state(
        connection,
        source_file,
        file_size,
        mtime_ns,
        status,
        rows_seen,
        rows_inserted,
        rows_rejected,
        last_error,
    )

    connection.commit()

    return {
        "status": status,
        "rows_seen": rows_seen,
        "rows_inserted": rows_inserted,
        "rows_rejected": rows_rejected,
        "last_error": last_error,
    }


def mark_file_error(
    connection,
    csv_file,
    data,
    file_size,
    mtime_ns,
    error,
):
    source_file = str(csv_file.resolve())

    raw_header = b""

    if data:
        raw_header = data.splitlines()[0] if data.splitlines() else b""

    record_error(
        connection,
        source_file,
        file_size,
        mtime_ns,
        1,
        str(error),
        raw_header,
    )

    update_file_state(
        connection,
        source_file,
        file_size,
        mtime_ns,
        "error",
        0,
        0,
        0,
        str(error),
    )

    connection.commit()


def process_file(
    connection,
    csv_file,
    quarantine_directory,
    force=False,
):
    data, file_size, mtime_ns = read_stable_snapshot(csv_file)
    source_file = str(csv_file.resolve())

    if (
        not force
        and unchanged_file(
            connection,
            source_file,
            file_size,
            mtime_ns,
        )
    ):
        return {
            "status": "skipped",
            "rows_seen": 0,
            "rows_inserted": 0,
            "rows_rejected": 0,
            "quarantine": None,
        }

    LOG.info("processing file=%s", csv_file)

    try:
        result = ingest_snapshot(
            connection,
            csv_file,
            data,
            file_size,
            mtime_ns,
        )

    except FileFormatError as exc:
        mark_file_error(
            connection,
            csv_file,
            data,
            file_size,
            mtime_ns,
            exc,
        )

        quarantine = quarantine_file(
            csv_file,
            quarantine_directory,
            data,
            file_size,
            mtime_ns,
        )

        LOG.error(
            "file rejected file=%s error=%s quarantine=%s",
            csv_file,
            exc,
            quarantine,
        )

        return {
            "status": "error",
            "rows_seen": 0,
            "rows_inserted": 0,
            "rows_rejected": 0,
            "quarantine": quarantine,
        }

    quarantine = None

    if result["rows_rejected"] > 0:
        quarantine = quarantine_file(
            csv_file,
            quarantine_directory,
            data,
            file_size,
            mtime_ns,
        )

        LOG.warning(
            "rows rejected file=%s rejected=%d quarantine=%s",
            csv_file,
            result["rows_rejected"],
            quarantine,
        )

    result["quarantine"] = quarantine
    return result


def resolve_paths(arguments):
    base_directory = arguments.base_dir.expanduser()

    incoming_directory = (
        arguments.incoming_dir.expanduser()
        if arguments.incoming_dir
        else base_directory / "incoming"
    )

    database_path = (
        arguments.database.expanduser()
        if arguments.database
        else base_directory / "database" / "sqm_network.sqlite"
    )

    quarantine_directory = (
        arguments.quarantine_dir.expanduser()
        if arguments.quarantine_dir
        else base_directory / "quarantine"
    )

    return (
        base_directory,
        incoming_directory,
        database_path,
        quarantine_directory,
    )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    arguments = parse_arguments()

    (
        base_directory,
        incoming_directory,
        database_path,
        quarantine_directory,
    ) = resolve_paths(arguments)

    database_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_directory.mkdir(parents=True, exist_ok=True)

    if not incoming_directory.is_dir():
        LOG.error(
            "incoming directory not found: %s",
            incoming_directory,
        )
        return 2

    files = sorted(incoming_directory.glob(arguments.pattern))

    summary = {
        "found": len(files),
        "processed": 0,
        "skipped": 0,
        "warning": 0,
        "error": 0,
        "unstable": 0,
        "rows_seen": 0,
        "rows_inserted": 0,
        "rows_rejected": 0,
    }

    try:
        connection = sqlite3.connect(
            str(database_path),
            timeout=30,
        )
        connection.execute("PRAGMA busy_timeout = 30000;")
        initialize_database(connection)

        for csv_file in files:
            try:
                result = process_file(
                    connection,
                    csv_file,
                    quarantine_directory,
                    force=arguments.force,
                )

            except FileChangedError as exc:
                summary["unstable"] += 1
                LOG.warning(
                    "file changed during read; retry later "
                    "file=%s error=%s",
                    csv_file,
                    exc,
                )
                continue

            except OSError as exc:
                summary["error"] += 1
                LOG.error(
                    "could not process file=%s error=%s",
                    csv_file,
                    exc,
                )
                continue

            status = result["status"]

            if status == "skipped":
                summary["skipped"] += 1
                continue

            summary["processed"] += 1
            summary[status] += 1

            summary["rows_seen"] += result["rows_seen"]
            summary["rows_inserted"] += result["rows_inserted"]
            summary["rows_rejected"] += result["rows_rejected"]

        total_database_rows = connection.execute(
            "SELECT COUNT(*) FROM sqm_readings;"
        ).fetchone()[0]

        connection.close()

    except sqlite3.Error as exc:
        LOG.exception("database failure: %s", exc)
        return 1

    print("Base directory:   {}".format(base_directory))
    print("Incoming:         {}".format(incoming_directory))
    print("Database:         {}".format(database_path))
    print("Quarantine:       {}".format(quarantine_directory))
    print("Files found:      {}".format(summary["found"]))
    print("Files processed:  {}".format(summary["processed"]))
    print("Files skipped:    {}".format(summary["skipped"]))
    print("Files warning:    {}".format(summary["warning"]))
    print("Files error:      {}".format(summary["error"]))
    print("Files unstable:   {}".format(summary["unstable"]))
    print("Rows seen:        {}".format(summary["rows_seen"]))
    print("Rows inserted:    {}".format(summary["rows_inserted"]))
    print("Rows rejected:    {}".format(summary["rows_rejected"]))
    print("Rows in database: {}".format(total_database_rows))

    has_problems = (
        summary["warning"] > 0
        or summary["error"] > 0
        or summary["unstable"] > 0
    )

    if arguments.strict and has_problems:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
