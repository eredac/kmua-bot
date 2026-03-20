"""drop_checkin_unique_constraint

Revision ID: g1h2i3j4k5l6
Revises: f1g2h3i4j5k6
Create Date: 2026-03-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, None] = "f1g2h3i4j5k6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the per-day unique constraint to allow multiple slot checkins per day."""
    with op.batch_alter_table("daily_checkin", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "uq_daily_checkin_per_user_chat_day", type_="unique"
        )


def downgrade() -> None:
    with op.batch_alter_table("daily_checkin", recreate="always") as batch_op:
        batch_op.create_unique_constraint(
            "uq_daily_checkin_per_user_chat_day",
            ["user_id", "chat_id", "checkin_date"],
        )
