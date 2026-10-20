"""Webhook outbound HTTP proxy.

Revision ID: 0009_webhook_proxy
Revises: 0008_drop_links_hmac
Create Date: 2026-10-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_webhook_proxy"
down_revision: Union[str, Sequence[str], None] = "0008_drop_links_hmac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webhooks",
        sa.Column("proxy_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "webhooks",
        sa.Column("proxy_host", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "webhooks",
        sa.Column("proxy_port", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "webhooks",
        sa.Column("proxy_login", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "webhooks",
        sa.Column("proxy_password", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("webhooks", "proxy_password")
    op.drop_column("webhooks", "proxy_login")
    op.drop_column("webhooks", "proxy_port")
    op.drop_column("webhooks", "proxy_host")
    op.drop_column("webhooks", "proxy_enabled")
