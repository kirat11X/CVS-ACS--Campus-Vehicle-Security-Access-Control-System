#!/usr/bin/env bash
# Fill placeholders locally; never commit a host name or private-key path.
set -euo pipefail
EC2_HOST="<EC2_HOST>"
KEY_PATH="<KEY_PATH>"
REMOTE_PATH="~/ml-assets/campus/"
rsync -avh --partial --append-verify -e "ssh -i ${KEY_PATH}" "$HOME/ml-assets/campus/" "${EC2_HOST}:${REMOTE_PATH}"
