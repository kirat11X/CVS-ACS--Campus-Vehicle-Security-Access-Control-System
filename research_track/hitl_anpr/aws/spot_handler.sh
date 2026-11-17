#!/bin/bash
# Polls the instance metadata (IMDSv2) for a spot interruption notice (about 2 minutes of warning). On notice:
# ask the trainer to stop at the next epoch boundary (STOP file) and push the data root, including the last
# verified checkpoint, to the encrypted bucket. A new instance resumes from that checkpoint
# (`anpr run-round` re-runs the round; train.py resumes from checkpoints/last.verified.pt).
set -uo pipefail
source /opt/anpr/env

token() {
  curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300"
}

while true; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "X-aws-ec2-metadata-token: $(token)" \
    "http://169.254.169.254/latest/meta-data/spot/instance-action")
  if [ "$code" = "200" ]; then
    echo "$(date -Is) spot interruption notice: stopping training and pushing checkpoints"
    touch "$DATA/runs/$ROUND/STOP" 2>/dev/null || true
    aws s3 sync "$DATA/runs/$ROUND/checkpoints/" "s3://$BUCKET/$PREFIX/data/runs/$ROUND/checkpoints/" \
      --only-show-errors --sse aws:kms --sse-kms-key-id "$KMS_KEY"
    aws s3 sync "$DATA/" "s3://$BUCKET/$PREFIX/data/" --only-show-errors --sse aws:kms --sse-kms-key-id "$KMS_KEY" \
      --exclude "runs/$ROUND/train/weights/*"
    sleep 300
  fi
  sleep 5
done
