#!/bin/bash
# EC2 boot script (Deep Learning Base OSS NVIDIA Driver AMI, Ubuntu 22.04). Rendered by launch_train.sh, which
# fills in the placeholder tokens. Pulls the data root from the encrypted bucket, runs (or resumes) one round in the
# training container, pushes results back, then shuts down; the spot handler and the idle watchdog run beside it.
set -euo pipefail
exec > >(tee -a /var/log/anpr-train.log) 2>&1

BUCKET="@BUCKET@"
PREFIX="@PREFIX@"
KMS_KEY="@KMS_KEY@"
IMAGE="@IMAGE@"
ROUND="@ROUND@"
REGION="@REGION@"
IDLE_MINUTES="@IDLE_MINUTES@"
DATA=/data

mkdir -p "$DATA" /opt/anpr
cat > /opt/anpr/spot_handler.sh <<'ANPR_EOF'
@SPOT_HANDLER@
ANPR_EOF
cat > /opt/anpr/idle_stop.sh <<'ANPR_EOF'
@IDLE_STOP@
ANPR_EOF
cat > /opt/anpr/env <<EOF
BUCKET=$BUCKET
PREFIX=$PREFIX
KMS_KEY=$KMS_KEY
DATA=$DATA
ROUND=$ROUND
IDLE_MINUTES=$IDLE_MINUTES
EOF

sync_up() {
  aws s3 sync "$DATA/" "s3://$BUCKET/$PREFIX/data/" --only-show-errors --sse aws:kms --sse-kms-key-id "$KMS_KEY"
}

# Watchdogs first, so an interruption during the data download is still handled.
install -m 0755 /opt/anpr/spot_handler.sh /usr/local/bin/anpr-spot-handler
install -m 0755 /opt/anpr/idle_stop.sh /usr/local/bin/anpr-idle-stop
cat > /etc/systemd/system/anpr-spot-handler.service <<'EOF'
[Unit]
Description=Spot interruption handler (stop training cleanly, push checkpoints)
[Service]
ExecStart=/usr/local/bin/anpr-spot-handler
Restart=always
EOF
cat > /etc/systemd/system/anpr-idle-stop.service <<'EOF'
[Unit]
Description=Shut the instance down when nothing has used the GPU for IDLE_MINUTES
[Service]
ExecStart=/usr/local/bin/anpr-idle-stop
Restart=always
EOF
systemctl daemon-reload
systemctl enable --now anpr-spot-handler anpr-idle-stop

aws s3 sync "s3://$BUCKET/$PREFIX/data/" "$DATA/" --only-show-errors
chown -R 1000:1000 "$DATA"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${IMAGE%%/*}"
docker pull "$IMAGE"

status=0
docker run --rm --gpus all --shm-size 8g -v "$DATA:/data" "$IMAGE" \
  run-round --round "$ROUND" --ignore-preflight || status=$?
sync_up
echo "round $ROUND finished with status $status; shutting down"
shutdown -h now
