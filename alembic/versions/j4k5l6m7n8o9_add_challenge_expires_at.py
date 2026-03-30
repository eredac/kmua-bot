"""add expires_at to challenge_record

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-03-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j4k5l6m7n8o9"
down_revision: Union[str, None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "challenge_record",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_column("challenge_record", "expires_at", schema="shared")
