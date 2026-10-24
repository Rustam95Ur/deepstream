"""Billing organization directory cache.

Revision ID: 0010_organizations
Revises: 0009_webhook_proxy
Create Date: 2026-10-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_organizations"
down_revision: Union[str, Sequence[str], None] = "0009_webhook_proxy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_organizations_is_active", "organizations", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_organizations_is_active", table_name="organizations")
    op.drop_table("organizations")
