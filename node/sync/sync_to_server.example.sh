#!/bin/bash
# Synchronize local CSV files from one Raspberry Pi node to the central server.

set -euo pipefail

DATA_DIR="/home/opd/sqm_opd/data/"
REMOTE_USER="irapuan"
REMOTE_HOST="SERVER_HOST"
REMOTE_DIR="/home/irapuan/sqm_network/incoming/SQM_OPD_001/"
SSH_KEY="/home/opd/.ssh/sqm_opd_ed25519"

ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_DIR}'"

rsync -av --partial --update \
  -e "ssh -i $SSH_KEY -o IdentitiesOnly=yes" \
  "${DATA_DIR}" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}"
