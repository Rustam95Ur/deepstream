"""Drop unique constraint on webhook login.

Revision ID: 0005_webhook_login_not_unique
Revises: 0004_webhook_login
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005_webhook_login_not_unique"
down_revision: Union[str, Sequence[str], None] = "0004_webhook_login"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_webhooks_login_lower")


def downgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX ux_webhooks_login_lower "
        "ON webhooks (lower(login)) WHERE login <> ''"
    )
