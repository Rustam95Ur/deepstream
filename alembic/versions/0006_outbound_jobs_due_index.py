"""Partial index for outbound job claim.

Revision ID: 0006_outbound_jobs_due_index
Revises: 0005_webhook_login_not_unique
Create Date: 2026-09-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0006_outbound_jobs_due_index"
down_revision: Union[str, Sequence[str], None] = "0005_webhook_login_not_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_outbound_jobs_due
        ON outbound_jobs (next_attempt_at, created_at)
        WHERE status IN ('pending', 'retrying')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_outbound_jobs_due")
