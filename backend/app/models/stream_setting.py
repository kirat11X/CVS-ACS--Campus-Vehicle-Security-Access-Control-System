from sqlalchemy import Column, String, Integer, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from backend.app.models.base import Base, TimestampMixin, utc_now


class GateStreamSetting(Base, TimestampMixin):
    """
    Configuration and persistence for Multi-Gate IP/mobile camera streams.
    Tracks IP, port, protocol, stream path, enabled state, and synchronized
    total adaptive FPS budget.
    """
    __tablename__ = "gate_stream_settings"

    gate_id = Column(String(30), ForeignKey("gates.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, default=False, nullable=False)
    ip_address = Column(String(100), default="192.168.1.100", nullable=False)
    port = Column(Integer, default=8080, nullable=False)
    protocol = Column(String(10), default="http", nullable=False)  # "http" or "rtsp"
    stream_path = Column(String(200), default="/video", nullable=False)
    custom_url = Column(String(500), nullable=True)
    total_fps_budget = Column(Float, default=15.0, nullable=False)

    gate = relationship("Gate")

    @property
    def stream_url(self) -> str:
        if self.custom_url and self.custom_url.strip():
            return self.custom_url.strip()
        path = self.stream_path if self.stream_path.startswith("/") else f"/{self.stream_path}"
        return f"{self.protocol.lower()}://{self.ip_address}:{self.port}{path}"
