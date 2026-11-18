from datetime import datetime
import ipaddress
import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}


def validate_camera_host(host: str) -> str:
    cleaned = host.strip()
    if not cleaned:
        raise ValueError("Host/IP address cannot be empty.")
    if cleaned in BLOCKED_HOSTS:
        raise ValueError("Access to cloud metadata endpoints is prohibited.")
    if "://" in cleaned or cleaned.startswith("file:"):
        raise ValueError("Host must be an IP or hostname, not a URL scheme.")
    return cleaned


class GateStreamConfigItem(BaseModel):
    gate_id: str
    gate_name: Optional[str] = None
    enabled: bool = False
    ip_address: str = "192.168.1.100"
    port: int = Field(8080, ge=1, le=65535)
    protocol: str = Field("http", pattern=r"^(http|rtsp)$")
    stream_path: str = Field("/video")
    custom_url: Optional[str] = None
    stream_url: str = ""
    is_running: bool = False
    effective_fps: float = 0.0
    actual_fps: float = 0.0
    last_seen_at: Optional[datetime] = None
    last_error: Optional[str] = None


class GateStreamSettingsResponse(BaseModel):
    total_fps_budget: float = 15.0
    active_gates_count: int = 1
    per_gate_target_fps: float = 15.0
    gates: List[GateStreamConfigItem] = []


class GateStreamConfigUpdateItem(BaseModel):
    gate_id: str = Field(..., min_length=1, max_length=30)
    gate_name: Optional[str] = Field(None, max_length=100)
    enabled: Optional[bool] = None
    ip_address: Optional[str] = Field(None, max_length=100)
    port: Optional[int] = Field(None, ge=1, le=65535)
    protocol: Optional[str] = Field(None, pattern=r"^(http|rtsp)$")
    stream_path: Optional[str] = Field(None, max_length=200)
    custom_url: Optional[str] = Field(None, max_length=500)

    @field_validator("ip_address")
    @classmethod
    def check_ip(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_camera_host(v)
        return v

    @field_validator("stream_path")
    @classmethod
    def check_path(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("/"):
            raise ValueError("Stream path must start with a leading slash '/'")
        return v


class GateStreamSettingsUpdate(BaseModel):
    total_fps_budget: Optional[float] = Field(None, ge=5.0, le=30.0)
    gates: Optional[List[GateStreamConfigUpdateItem]] = None


class StreamTestRequest(BaseModel):
    ip_address: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    protocol: Optional[str] = Field(None, pattern=r"^(http|rtsp)$")
    stream_path: Optional[str] = None
    custom_url: Optional[str] = None

    @field_validator("ip_address")
    @classmethod
    def check_test_ip(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_camera_host(v)
        return v


class StreamTestResponse(BaseModel):
    status: str  # "ok" or "error"
    gate_id: Optional[str] = None
    tested_url: str
    latency_ms: Optional[float] = None
    stream_type: Optional[str] = None
    message: str
