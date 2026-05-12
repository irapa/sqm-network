# Central Server Setup

The central server receives CSV files from one or more Raspberry Pi acquisition nodes and ingests them into a central SQLite database.

Assumed server user:

```text
irapuan
```

Assumed base directory:

```text
/home/irapuan/sqm_network
```

## Create directory structure

```bash
mkdir -p ~/sqm_network/incoming/SQM_OPD_001
mkdir -p ~/sqm_network/archive
mkdir -p ~/sqm_network/database
mkdir -p ~/sqm_network/scripts
mkdir -p ~/sqm_network/systemd
```

For each future sensor:

```bash
mkdir -p ~/sqm_network/incoming/SQM_OPD_002
mkdir -p ~/sqm_network/incoming/SQM_OPD_003
```

## Install ingest script

```bash
cp server/scripts/ingest_csv.py ~/sqm_network/scripts/
chmod +x ~/sqm_network/scripts/ingest_csv.py
```

Run manually:

```bash
python3 ~/sqm_network/scripts/ingest_csv.py
```

Verify:

```bash
sqlite3 ~/sqm_network/database/sqm_network.sqlite \
"SELECT sensor_id, COUNT(*) FROM sqm_readings GROUP BY sensor_id;"
```

## Install systemd ingest timer

```bash
sudo cp systemd/server/sqm-ingest.service /etc/systemd/system/
sudo cp systemd/server/sqm-ingest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sqm-ingest.timer
```

Test:

```bash
sudo systemctl start sqm-ingest.service
sudo journalctl -u sqm-ingest.service -n 50
```
