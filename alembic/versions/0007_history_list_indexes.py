"""Indexes for history list filters on trigger_events / send_events.

Revision ID: 0007_history_list_indexes
Revises: 0006_outbound_jobs_due_index
Create Date: 2026-09-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0007_history_list_indexes"
down_revision: Union[str, Sequence[str], None] = "0006_outbound_jobs_due_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trigger_events_type_created
            ON trigger_events (trigger_type, created_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trigger_events_camera_created
            ON trigger_events (camera_id, created_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trigger_events_category_created
            ON trigger_events (category, created_at DESC, id DESC)
            """
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_trigger_events_camera_id")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_send_events_status_created
            ON send_events (status, created_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_send_events_sink_created
            ON send_events (sink, created_at DESC, id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_outbound_jobs_status_updated
            ON outbound_jobs (status, updated_at DESC, id DESC)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_outbound_jobs_status_updated")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_send_events_sink_created")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_send_events_status_created")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_trigger_events_camera_id
            ON trigger_events (camera_id)
            """
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_trigger_events_category_created"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_trigger_events_camera_created")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_trigger_events_type_created")
