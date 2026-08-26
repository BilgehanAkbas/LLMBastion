from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from .database import Base


class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    priority = Column(Integer, nullable=False)
    complete = Column(Boolean, default=False, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    role = Column(String, default="user", nullable=False)
    phone_number = Column(String, nullable=False)

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
