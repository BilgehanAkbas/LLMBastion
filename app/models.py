from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from .database import Base


class GatewayRequest(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(36), unique=True, index=True, nullable=False)
    risk_score = Column(Float, nullable=False)
    action = Column(String, nullable=False)
    latency_ms = Column(Float, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class DetectorResult(Base):
    __tablename__ = "detector_results"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(
        String(36),
        ForeignKey("requests.request_id"),
        index=True,
        nullable=False,
    )
    detector_name = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    evidence = Column(Text, nullable=True)
    latency_ms = Column(Float, nullable=False)
