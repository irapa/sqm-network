# Operations Guide

## Raspberry commands

Check collector:

```bash
systemctl status sqm-collector
journalctl -u sqm-collector -f
```

Stop/start collector:

```bash
sudo systemctl stop sqm-collector
sudo systemctl start sqm-collector
```

Check sync:

```bash
systemctl status sqm-sync.timer
systemctl list-timers | grep sqm-sync
sudo systemctl start sqm-sync.service
journalctl -u sqm-sync.service -n 50
```

Check local CSV:

```bash
ls -lh ~/sqm_opd/data/
tail -n 5 ~/sqm_opd/data/*.csv
```

## Server commands

Check ingest:

```bash
systemctl status sqm-ingest.timer
systemctl list-timers | grep sqm-ingest
sudo systemctl start sqm-ingest.service
sudo journalctl -u sqm-ingest.service -n 50
```

Check database:

```bash
sqlite3 ~/sqm_network/database/sqm_network.sqlite \
"SELECT sensor_id, COUNT(*) FROM sqm_readings GROUP BY sensor_id;"
```

Latest readings:

```bash
sqlite3 ~/sqm_network/database/sqm_network.sqlite \
"SELECT local_time, sensor_id, mag_arcsec2, sun_alt_deg, moon_alt_deg, usable_dark_sky
 FROM sqm_readings
 ORDER BY utc_time DESC
 LIMIT 10;"
```

## Adding a new station

On the new Raspberry:

1. Change `sensor_id`, e.g.:

```yaml
sensor_id: SQM_OPD_002
site_name: Brazopolis
```

2. Change remote destination:

```text
/home/irapuan/sqm_network/incoming/SQM_OPD_002/
```

3. On server:

```bash
mkdir -p ~/sqm_network/incoming/SQM_OPD_002
```

The same `ingest_csv.py` will ingest all sensors automatically.
