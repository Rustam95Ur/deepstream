"""Initial cameras, links, trigger and send history.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cameras",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("main_uri", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "external_id", sa.String(length=128), nullable=False, server_default=""
        ),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "links",
        sa.Column("kind", sa.String(length=64), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "trigger_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column(
            "camera_id", sa.String(length=128), nullable=False, server_default=""
        ),
        sa.Column(
            "trigger_type", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column(
            "category", sa.String(length=64), nullable=False, server_default="incident"
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_trigger_events_event_id"),
    )
    op.create_index("ix_trigger_events_created_at", "trigger_events", ["created_at"])
    op.create_index("ix_trigger_events_camera_id", "trigger_events", ["camera_id"])
    op.create_table(
        "send_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("sink", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_send_events_created_at", "send_events", ["created_at"])
    op.create_index("ix_send_events_event_id", "send_events", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_send_events_event_id", table_name="send_events")
    op.drop_index("ix_send_events_created_at", table_name="send_events")
    op.drop_table("send_events")
    op.drop_index("ix_trigger_events_camera_id", table_name="trigger_events")
    op.drop_index("ix_trigger_events_created_at", table_name="trigger_events")
    op.drop_table("trigger_events")
    op.drop_table("links")
    op.drop_table("cameras")
