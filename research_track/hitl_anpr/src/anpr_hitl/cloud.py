"""S3 helpers. Nothing here runs unless cfg.s3.enabled is true and a bucket is configured.

Objects are written with SSE-KMS; the bucket itself (private, versioned, lifecycle-limited) is created
by aws/cloudformation.yaml, never from Python.
"""

from __future__ import annotations

from pathlib import Path

from anpr_hitl.config import Config


class S3Disabled(RuntimeError):
    pass


def _client(cfg: Config):
    if not cfg.s3.enabled or not cfg.s3.bucket:
        raise S3Disabled("S3 is disabled in config.yaml (s3.enabled=false or no bucket)")
    if not cfg.s3.kms_key_id:
        raise S3Disabled("s3.kms_key_id is not set: uploads must name the stack's KMS key")
    import boto3

    return boto3.client("s3", region_name=cfg.s3.region)


def s3_key(cfg: Config, *parts: str) -> str:
    return "/".join([cfg.s3.prefix.strip("/"), *(p.strip("/") for p in parts)])


def upload_checkpoint(cfg: Config, path: Path, run_name: str) -> str:
    key = s3_key(cfg, "checkpoints", run_name, Path(path).name)
    _client(cfg).upload_file(str(path), cfg.s3.bucket, key,
                             ExtraArgs={"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": cfg.s3.kms_key_id})
    return key


def download_checkpoint(cfg: Config, run_name: str, dest: Path) -> bool:
    """Fetch the latest verified checkpoint of a run (used after a spot interruption). False if none."""
    client = _client(cfg)
    key = s3_key(cfg, "checkpoints", run_name, "last.verified.pt")
    try:
        client.head_object(Bucket=cfg.s3.bucket, Key=key)
    except client.exceptions.ClientError:
        return False
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    client.download_file(cfg.s3.bucket, key, str(dest))
    return True
