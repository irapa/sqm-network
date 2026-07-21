#!/usr/bin/env python3
"""Synchronize one SQM acquisition node with the central server."""

import argparse
import pathlib
import re
import shlex
import subprocess
import sys

import yaml


STATION_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,63}$")
HOST_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
USER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
REMOTE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9_./-]+$")

PLACEHOLDERS = {
    "SERVER_HOST",
    "REMOTE_USER",
}


class SyncConfigError(RuntimeError):
    """Raised when synchronization configuration is invalid."""


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Synchronize SQM CSV files with the central server."
    )

    parser.add_argument(
        "--config",
        required=True,
        type=pathlib.Path,
        help="Node YAML configuration file.",
    )

    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate and display the configuration without connecting.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run rsync in dry-run mode without modifying the server.",
    )

    return parser.parse_args()


def read_yaml(path):
    path = path.expanduser()

    if not path.is_file():
        raise SyncConfigError(
            "Configuration file not found: {}".format(path)
        )

    try:
        with path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
    except OSError as exc:
        raise SyncConfigError(
            "Could not read {}: {}".format(path, exc)
        ) from exc
    except yaml.YAMLError as exc:
        raise SyncConfigError(
            "Invalid YAML in {}: {}".format(path, exc)
        ) from exc

    if not isinstance(raw, dict):
        raise SyncConfigError(
            "The configuration root must be a YAML mapping."
        )

    return raw


def require_boolean(value, field_name):
    if not isinstance(value, bool):
        raise SyncConfigError(
            "{} must be true or false.".format(field_name)
        )

    return value


def normalize_config(raw):
    hierarchical = isinstance(raw.get("station"), dict)

    try:
        if hierarchical:
            station = raw["station"]
            storage = raw["storage"]
            server = raw["server"]

            station_id = str(station["id"]).strip()
            data_dir = pathlib.Path(
                str(storage["data_dir"])
            ).expanduser()

            enabled = require_boolean(
                server.get("enabled", True),
                "server.enabled",
            )

            hostname = str(server["hostname"]).strip()
            username = str(server["username"]).strip()
            ssh_key = pathlib.Path(
                str(server["ssh_key"])
            ).expanduser()

            remote_base_path = str(
                server["remote_base_path"]
            ).rstrip("/")

            remote_dir = "{}/{}/".format(
                remote_base_path,
                station_id,
            )

            legacy_format = False

        else:
            station_id = str(raw["sensor_id"]).strip()
            data_dir = pathlib.Path(
                str(raw["data_dir"])
            ).expanduser()

            server = raw["server"]

            enabled = require_boolean(
                server.get("enabled", True),
                "server.enabled",
            )

            hostname = str(server["hostname"]).strip()
            username = str(server["username"]).strip()
            ssh_key = pathlib.Path(
                str(
                    server.get(
                        "ssh_key",
                        "~/.ssh/sqm_opd_ed25519",
                    )
                )
            ).expanduser()

            remote_dir = str(server["remote_path"])
            legacy_format = True

    except (KeyError, TypeError, ValueError) as exc:
        raise SyncConfigError(
            "Missing or invalid configuration value: {}".format(exc)
        ) from exc

    config = {
        "station_id": station_id,
        "data_dir": data_dir,
        "enabled": enabled,
        "hostname": hostname,
        "username": username,
        "ssh_key": ssh_key,
        "remote_dir": remote_dir,
        "legacy_format": legacy_format,
    }

    validate_config(config)
    return config


def validate_config(config):
    if not STATION_ID_PATTERN.fullmatch(config["station_id"]):
        raise SyncConfigError(
            "Invalid station identifier: {!r}".format(
                config["station_id"]
            )
        )

    if not config["hostname"]:
        raise SyncConfigError("server.hostname cannot be empty.")

    if not HOST_PATTERN.fullmatch(config["hostname"]):
        raise SyncConfigError(
            "Invalid server hostname: {!r}".format(
                config["hostname"]
            )
        )

    if not config["username"]:
        raise SyncConfigError("server.username cannot be empty.")

    if not USER_PATTERN.fullmatch(config["username"]):
        raise SyncConfigError(
            "Invalid server username: {!r}".format(
                config["username"]
            )
        )

    remote_dir = config["remote_dir"]

    if not REMOTE_PATH_PATTERN.fullmatch(remote_dir):
        raise SyncConfigError(
            "Invalid remote directory: {!r}".format(remote_dir)
        )

    remote_parts = pathlib.PurePosixPath(remote_dir).parts

    if ".." in remote_parts:
        raise SyncConfigError(
            "The remote directory cannot contain '..'."
        )


def print_summary(config, config_path):
    print("Synchronization configuration valid")
    print("  file: {}".format(config_path.resolve()))
    print("  station_id: {}".format(config["station_id"]))
    print("  enabled: {}".format(config["enabled"]))
    print("  data_dir: {}".format(config["data_dir"]))
    print(
        "  destination: {}@{}:{}".format(
            config["username"],
            config["hostname"],
            config["remote_dir"],
        )
    )
    print("  ssh_key: {}".format(config["ssh_key"]))
    print(
        "  data_dir_exists: {}".format(
            config["data_dir"].is_dir()
        )
    )
    print(
        "  ssh_key_exists: {}".format(
            config["ssh_key"].is_file()
        )
    )
    print("  legacy_format: {}".format(
        config["legacy_format"]
    ))


def check_runtime_paths(config):
    if config["hostname"] in PLACEHOLDERS:
        raise SyncConfigError(
            "Replace placeholder server hostname: {}".format(
                config["hostname"]
            )
        )

    if config["username"] in PLACEHOLDERS:
        raise SyncConfigError(
            "Replace placeholder server username: {}".format(
                config["username"]
            )
        )

    if not config["data_dir"].is_dir():
        raise SyncConfigError(
            "Local data directory not found: {}".format(
                config["data_dir"]
            )
        )

    if not config["ssh_key"].is_file():
        raise SyncConfigError(
            "SSH private key not found: {}".format(
                config["ssh_key"]
            )
        )


def build_ssh_arguments(config):
    return [
        "ssh",
        "-i",
        str(config["ssh_key"]),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
    ]


def run_command(command):
    print("+ {}".format(shlex.join(command)), flush=True)
    subprocess.run(command, check=True)


def synchronize(config, dry_run=False):
    if not config["enabled"]:
        print(
            "Synchronization disabled for station {}.".format(
                config["station_id"]
            )
        )
        return 0

    check_runtime_paths(config)

    target = "{}@{}".format(
        config["username"],
        config["hostname"],
    )

    ssh_arguments = build_ssh_arguments(config)

    if not dry_run:
        remote_mkdir = "mkdir -p -- {}".format(
            shlex.quote(config["remote_dir"])
        )

        run_command(
            ssh_arguments
            + [
                target,
                remote_mkdir,
            ]
        )

    ssh_transport = shlex.join(ssh_arguments)

    rsync_command = [
        "rsync",
        "-a",
        "--checksum",
        "--partial",
        "--delay-updates",
        "--itemize-changes",
        "--prune-empty-dirs",
        "--include=*.csv",
        "--exclude=*",
        "--timeout=60",
    ]

    if dry_run:
        rsync_command.append("--dry-run")

    rsync_command.extend([
        "-e",
        ssh_transport,
        str(config["data_dir"]) + "/",
        "{}:{}/".format(
            target,
            config["remote_dir"].rstrip("/"),
        ),
    ])

    run_command(rsync_command)
    return 0


def main():
    arguments = parse_arguments()

    try:
        raw = read_yaml(arguments.config)
        config = normalize_config(raw)

        if arguments.check_config:
            print_summary(config, arguments.config)
            return 0

        return synchronize(
            config,
            dry_run=arguments.dry_run,
        )

    except SyncConfigError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(
            "ERROR: command failed with exit status {}".format(
                exc.returncode
            ),
            file=sys.stderr,
        )
        return exc.returncode
    except KeyboardInterrupt:
        print("Synchronization interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
