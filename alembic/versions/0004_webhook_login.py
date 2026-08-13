"""Webhook login/password for inbound camera API.

Revision ID: 0004_webhook_login
Revises: 0003_webhooks
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_webhook_login"
down_revision: Union[str, Sequence[str], None] = "0003_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webhooks",
        sa.Column("login", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "webhooks",
        sa.Column("password_hash", sa.Text(), nullable=False, server_default=""),
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_webhooks_login_lower "
        "ON webhooks (lower(login)) WHERE login <> ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_webhooks_login_lower")
    op.drop_column("webhooks", "password_hash")
    op.drop_column("webhooks", "login")
