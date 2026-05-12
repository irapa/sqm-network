# Raspberry Pi Deployment

Assumed user:

```text
opd
```

Assumed deployment directory:

```text
/home/opd/sqm_opd
```

## Directory layout

```bash
mkdir -p ~/sqm_opd/{collector,data,logs,systemd}
```

Copy files:

```bash
cp collector/sqm_collector.py ~/sqm_opd/collector/
cp collector/config.example.yaml ~/sqm_opd/collector/config.yaml
cp collector/sync_to_server.example.sh ~/sqm_opd/collector/sync_to_server.sh
chmod +x ~/sqm_opd/collector/*.py
chmod +x ~/sqm_opd/collector/*.sh
```

Edit:

```bash
nano ~/sqm_opd/collector/config.yaml
nano ~/sqm_opd/collector/sync_to_server.sh
```

## Run manually

```bash
cd ~/sqm_opd
source .venv/bin/activate
python collector/sqm_collector.py
```

Stop with `Ctrl+C`.

## Install collector service

```bash
sudo cp systemd/raspberry/sqm-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sqm-collector
```

Check:

```bash
systemctl status sqm-collector
journalctl -u sqm-collector -f
```

## Configure SSH key for sync

On Raspberry:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/sqm_opd_ed25519 -C "sqm-opd-001"
ssh-copy-id -i ~/.ssh/sqm_opd_ed25519.pub irapuan@192.168.1.49
```

Test:

```bash
ssh -i ~/.ssh/sqm_opd_ed25519 -o IdentitiesOnly=yes irapuan@192.168.1.49
```

## Install sync service and timer

```bash
sudo cp systemd/raspberry/sqm-sync.service /etc/systemd/system/
sudo cp systemd/raspberry/sqm-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sqm-sync.timer
```

Test:

```bash
sudo systemctl start sqm-sync.service
journalctl -u sqm-sync.service -n 50
```
