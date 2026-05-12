# Grafana Setup

Grafana should run on the central server, not on the Raspberry Pi.

## Start Grafana

```bash
sudo systemctl enable --now grafana-server
```

Open:

```text
http://localhost:3000
```

or from another machine:

```text
http://SERVER_IP:3000
```

## SQLite plugin

```bash
sudo grafana-cli plugins install frser-sqlite-datasource
sudo systemctl restart grafana-server
```

## Configure datasource

| Field | Value |
|---|---|
| Name | `sqm-network` |
| Path | `/home/irapuan/sqm_network/database/sqm_network.sqlite` |
| Path Prefix | `file:` |
| Path Options | `_pragma=query_only(1)` |
| Secure Path | leave blank |
| Attach Limit | `0` |

If Grafana cannot access `/home`, check:

```bash
systemctl show grafana-server -p ProtectHome
```

If needed:

```bash
sudo systemctl edit grafana-server
```

Content:

```ini
[Service]
ProtectHome=false
```

Then:

```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl restart grafana-server
```

## Panel queries

See `grafana/sql/`.
