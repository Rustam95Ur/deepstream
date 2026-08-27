"""Webhooks, outbound job queue, per-camera trigger types.

Revision ID: 0003_webhooks
Revises: 0002_users
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_webhooks"
down_revision: Union[str, Sequence[str], None] = "0002_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "enabled_triggers", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_table(
        "webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("hmac_secret", sa.Text(), nullable=False, server_default=""),
        sa.Column("timeout_sec", sa.Float(), nullable=False, server_default="5"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webhooks_enabled", "webhooks", ["enabled"])
    op.create_table(
        "outbound_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("webhook_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="6"),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_outbound_jobs_event_id", "outbound_jobs", ["event_id"])
    op.create_index(
        "ix_outbound_jobs_status_next", "outbound_jobs", ["status", "next_attempt_at"]
    )
    op.create_index("ix_outbound_jobs_webhook_id", "outbound_jobs", ["webhook_id"])


def downgrade() -> None:
    op.drop_index("ix_outbound_jobs_webhook_id", table_name="outbound_jobs")
    op.drop_index("ix_outbound_jobs_status_next", table_name="outbound_jobs")
    op.drop_index("ix_outbound_jobs_event_id", table_name="outbound_jobs")
    op.drop_table("outbound_jobs")
    op.drop_index("ix_webhooks_enabled", table_name="webhooks")
    op.drop_table("webhooks")
    op.drop_column("cameras", "enabled_triggers")
