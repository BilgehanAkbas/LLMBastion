"""create audit tables

Revision ID: 0001_create_audit_tables
Revises:
Create Date: 2026-09-02
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_create_audit_tables"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "requests",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "request_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "risk_score",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(),
            nullable=False,
        ),
        sa.Column(
            "latency_ms",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        "ix_requests_id",
        "requests",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_requests_request_id",
        "requests",
        ["request_id"],
        unique=True,
    )

    op.create_table(
        "detector_results",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "request_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "detector_name",
            sa.String(),
            nullable=False,
        ),
        sa.Column(
            "score",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "evidence",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "latency_ms",
            sa.Float(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.request_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_detector_results_id",
        "detector_results",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_detector_results_request_id",
        "detector_results",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_detector_results_request_id",
        table_name="detector_results",
    )
    op.drop_index(
        "ix_detector_results_id",
        table_name="detector_results",
    )
    op.drop_table("detector_results")

    op.drop_index(
        "ix_requests_request_id",
        table_name="requests",
    )
    op.drop_index(
        "ix_requests_id",
        table_name="requests",
    )
    op.drop_table("requests")
