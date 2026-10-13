from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from backend.app.models.base import Base

class HealthCheckRecord(Base):
    __tablename__ = "health_checks"

    id = Column(Integer, primary_key=True, index=True)
    component = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
