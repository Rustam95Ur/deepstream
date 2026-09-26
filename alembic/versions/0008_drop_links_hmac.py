"""Drop unused links table and webhooks.hmac_secret.

Revision ID: 0008_drop_links_hmac
Revises: 0007_history_list_indexes
Create Date: 2026-09-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_drop_links_hmac"
down_revision: Union[str, Sequence[str], None] = "0007_history_list_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("links")
    op.drop_column("webhooks", "hmac_secret")


def downgrade() -> None:
    op.add_column(
        "webhooks",
        sa.Column(
            "hmac_secret",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.create_table(
        "links",
        sa.Column("kind", sa.String(length=64), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
