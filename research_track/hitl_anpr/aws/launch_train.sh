#!/bin/bash
# Launch one training round on a spot GPU instance. DRY RUN unless CONFIRM=1: prints the rendered user data
# summary, the run-instances request and the cost formula, and calls nothing that costs money.
# With CONFIRM=1 it first runs `aws ec2 run-instances --dry-run` (a permission check, no instance), then launches.
#
# Required: BUCKET KMS_KEY IMAGE INSTANCE_PROFILE ROUND   Optional: REGION INSTANCE_TYPE IDLE_MINUTES MARKET
#           SUBNET SECURITY_GROUP PRICE_PER_HOUR EST_HOURS OWNER
set -euo pipefail
cd "$(dirname "$0")"

: "${BUCKET:?set BUCKET}" "${KMS_KEY:?set KMS_KEY}" "${IMAGE:?set IMAGE (ECR uri:tag)}"
: "${INSTANCE_PROFILE:?set INSTANCE_PROFILE}" "${ROUND:?set ROUND}"
REGION="${REGION:-ap-south-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g6.2xlarge}"
IDLE_MINUTES="${IDLE_MINUTES:-15}"
MARKET="${MARKET:-spot}"
PREFIX="${PREFIX:-campus-anpr-hitl}"
OWNER="${OWNER:-pec-honours}"
AMI_PARAM=/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id

user_data=$(python3 - "$BUCKET" "$PREFIX" "$KMS_KEY" "$IMAGE" "$ROUND" "$REGION" "$IDLE_MINUTES" <<'EOF'
import sys
from pathlib import Path
keys = ["BUCKET", "PREFIX", "KMS_KEY", "IMAGE", "ROUND", "REGION", "IDLE_MINUTES"]
text = Path("user_data.sh").read_text()
for k, v in zip(keys, sys.argv[1:]):
    text = text.replace(f"@{k}@", v)
text = text.replace("@SPOT_HANDLER@", Path("spot_handler.sh").read_text().rstrip())
text = text.replace("@IDLE_STOP@", Path("idle_stop.sh").read_text().rstrip())
import re
left = re.findall(r"@[A-Z_]+@", text)
assert not left, f"unrendered placeholders: {left}"
sys.stdout.write(text)
EOF
)
size=$(printf '%s' "$user_data" | wc -c)
[ "$size" -lt 16000 ] || { echo "user data is $size bytes (EC2 limit 16 KB)" >&2; exit 1; }

market_opts=()
if [ "$MARKET" = "spot" ]; then
  market_opts=(--instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}')
fi
net_opts=()
[ -n "${SUBNET:-}" ] && net_opts+=(--subnet-id "$SUBNET")
[ -n "${SECURITY_GROUP:-}" ] && net_opts+=(--security-group-ids "$SECURITY_GROUP")
tags="ResourceType=instance,Tags=[{Key=Project,Value=campus-anpr-hitl},{Key=Owner,Value=$OWNER},{Key=Round,Value=$ROUND},{Key=AutoStop,Value=${IDLE_MINUTES}min}]"
vol_tags="ResourceType=volume,Tags=[{Key=Project,Value=campus-anpr-hitl},{Key=Owner,Value=$OWNER}]"

echo "== launch plan (round $ROUND) =="
echo "region=$REGION type=$INSTANCE_TYPE market=$MARKET image=$IMAGE bucket=$BUCKET/$PREFIX"
echo "root volume: 100 GB gp3, encrypted, deleted on termination; IMDSv2 only; idle shutdown after $IDLE_MINUTES min"
echo "user data: $size bytes (spot handler + idle watchdog embedded)"
echo "cost: hours = images x epochs / (images_per_s x 3600); you pay hours x PRICE_PER_HOUR (+ storage, transfer)."
if [ -n "${PRICE_PER_HOUR:-}" ] && [ -n "${EST_HOURS:-}" ]; then
  python3 -c "print(f'estimate: {float(\"$EST_HOURS\"):.2f} h x {float(\"$PRICE_PER_HOUR\"):.3f} USD/h = {float(\"$EST_HOURS\") * float(\"$PRICE_PER_HOUR\"):.2f} USD')"
else
  echo "estimate: set PRICE_PER_HOUR (current $MARKET price for $INSTANCE_TYPE in $REGION) and EST_HOURS"
fi

args=(ec2 run-instances --region "$REGION" --instance-type "$INSTANCE_TYPE" --count 1
      --image-id "resolve:ssm:$AMI_PARAM" --iam-instance-profile "Name=$INSTANCE_PROFILE"
      --instance-initiated-shutdown-behavior terminate
      --metadata-options "HttpTokens=required,HttpEndpoint=enabled"
      --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=100,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}'
      --tag-specifications "$tags" "$vol_tags" --user-data "$user_data"
      "${market_opts[@]}" "${net_opts[@]}")

if [ "${CONFIRM:-0}" != "1" ]; then
  echo "DRY RUN: nothing launched. Re-run with CONFIRM=1 to launch (this starts a billed GPU instance)."
  exit 0
fi
command -v aws >/dev/null || { echo "aws CLI not installed" >&2; exit 1; }
echo "permission check (aws --dry-run, no instance is created)..."
out=$(aws "${args[@]}" --dry-run 2>&1 || true)
echo "$out" | grep -q "DryRunOperation" || { echo "$out" >&2; exit 1; }
aws "${args[@]}" --query 'Instances[0].InstanceId' --output text
