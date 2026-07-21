# Production deployment

This document records the first production deployment of the distributed
LNA SQM Network architecture.

Deployment date: 2026-07-21

## Architecture

```text
Unihedron SQM-LU
        |
        v
Raspberry Pi acquisition node
        |
        | SSH + rsync
        v
Central server incoming directory
        |
        | resilient CSV ingestion
        v
SQLite database
        |
        v
Grafana and scientific analysis
```

## First production station

- Station ID: `SQM_OPD_001`
- Node hostname: `sqm-opd`
- Site code: `OPD`
- Sensor model: Unihedron SQM-LU
- Sensor serial number: `5620`
- Acquisition cadence: 60 seconds
- Acquisition window: Sun altitude at or below -12 degrees
- Scientific dark-sky criterion:
  - Sun altitude below -18 degrees
  - Moon below the horizon

## Acquisition node

Production paths:

```text
/opt/sqm-node/venv
/usr/local/lib/sqm-node/sqm_collector.py
/usr/local/lib/sqm-node/sync_to_server.py
/etc/sqm-node/config.yaml
/etc/sqm-node/keys/sync_ed25519
/var/lib/sqm-node/data
/var/log/sqm-node
```

Systemd units:

```text
sqm-collector.service
sqm-sync.service
sqm-sync.timer
```

Expected state:

```text
sqm-collector.service: enabled, active
sqm-sync.timer: enabled, active
sqm-sync.service: inactive after a successful oneshot execution
```

The synchronization timer normally runs every five minutes.

## Central server

Operational paths:

```text
<server-home>/sqm_network/incoming
<server-home>/sqm_network/database/sqm_network.sqlite
<server-home>/sqm_network/quarantine
/usr/local/lib/sqm-server/ingest_csv.py
```

Systemd units:

```text
sqm-ingest-v2.service
sqm-ingest-v2.timer
```

Expected state:

```text
sqm-ingest-v2.timer: enabled, active
sqm-ingest-v2.service: inactive after a successful oneshot execution
```

The previous `sqm-ingest.timer` remains installed but disabled during the
initial stabilization period.

## Data integrity

The collector writes each CSV row as one encoded append operation.

The central ingestor:

- checks that a source file is stable while being read;
- validates the 11-column CSV header;
- rejects malformed rows without stopping other files;
- records file status and ingestion errors in SQLite;
- quarantines malformed input snapshots;
- relies on database uniqueness constraints to avoid duplicate readings.

## Basic health checks

Node:

```bash
systemctl is-active sqm-collector.service
systemctl is-active sqm-sync.timer
systemctl show sqm-sync.service -p Result -p ExecMainStatus
journalctl -u sqm-collector.service -n 30 --no-pager
journalctl -u sqm-sync.service -n 30 --no-pager
```

Server:

```bash
systemctl is-active sqm-ingest-v2.timer
systemctl show sqm-ingest-v2.service -p Result -p ExecMainStatus
journalctl -u sqm-ingest-v2.service -n 50 --no-pager
sqlite3 <database-path> "PRAGMA quick_check;"
```

The SQLite integrity check must return:

```text
ok
```

## Configuration and secrets

Operational YAML files, SSH private keys, CSV data and SQLite databases must
not be committed to the repository.

Only example configurations with placeholder server information belong in
version control.

## Rollback

The previous node installation is temporarily retained under:

```text
/home/opd/sqm_opd
```

The previous server ingestion units are also retained but disabled.

Rollback must include:

1. stopping the new timers and services;
2. copying any newly collected CSV data back to the old data directory;
3. restoring the saved systemd units;
4. reloading systemd;
5. enabling and validating the previous services.

Database restoration should only be performed when an integrity check fails,
not merely because a service execution fails.
