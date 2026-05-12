# Installation Guide

This document describes the installation of the SQM-OPD distributed monitoring system.

The architecture has two parts:

1. **Raspberry Pi acquisition node**: reads the SQM-LU and writes daily CSV files.
2. **Central server**: receives CSV files, ingests them into SQLite and serves dashboards through Grafana.

## Raspberry Pi system packages

Tested with Raspberry Pi OS / Debian 13 (Trixie), 64-bit.

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv rsync usbutils sqlite3 nano
```

Add the acquisition user to `dialout`:

```bash
sudo usermod -aG dialout opd
```

Log out and log in again.

Check:

```bash
groups
ls /dev/ttyUSB*
```

## Python environment on Raspberry

```bash
cd ~
git clone https://github.com/SEU_USUARIO/sqm-opd.git
cd sqm-opd

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-collector.txt
```

If your SD card is small, do not install `pandas`, `matplotlib`, Grafana or QGIS on the Raspberry.

## Manual SQM test

```bash
source .venv/bin/activate
python
```

```python
import serial, time
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
time.sleep(2)
ser.write(b"rx\n")
print(ser.readline().decode().strip())
ser.close()
```

Expected output:

```text
r, 21.43m,0000000021Hz,0000000000c,0000000.000s, 024.8C
```

## Server packages

On the desktop/server:

```bash
sudo apt install sqlite3 rsync openssh-server python3
```

For openSUSE:

```bash
sudo zypper install sqlite3 rsync openssh python3
```

For Fedora:

```bash
sudo dnf install sqlite rsync openssh-server python3
```
