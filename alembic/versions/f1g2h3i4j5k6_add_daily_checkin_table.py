"""add_daily_checkin_table

Revision ID: f1g2h3i4j5k6
Revises: e1f2g3h4i5j6
Create Date: 2026-03-04 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1g2h3i4j5k6"
down_revision: Union[str, None] = "e1f2g3h4i5j6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("daily_checkin"):
        op.create_table(
            "daily_checkin",
            sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("checkin_date", sa.String(10), nullable=False),
            sa.Column("checkin_type", sa.String(20), nullable=False),
            sa.Column("points_earned", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["user_data.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["chat_id"], ["chat_data.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "chat_id", "checkin_date",
                name="uq_daily_checkin_per_user_chat_day",
            ),
        )
        op.create_index(
            op.f("ix_daily_checkin_id"), "daily_checkin", ["id"], unique=False
        )
        op.create_index(
            op.f("ix_daily_checkin_user_id"), "daily_checkin", ["user_id"], unique=False
        )
        op.create_index(
            op.f("ix_daily_checkin_chat_id"), "daily_checkin", ["chat_id"], unique=False
        )
        op.create_index(
            op.f("ix_daily_checkin_checkin_date"),
            "daily_checkin",
            ["checkin_date"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_daily_checkin_checkin_date"), table_name="daily_checkin")
    op.drop_index(op.f("ix_daily_checkin_chat_id"), table_name="daily_checkin")
    op.drop_index(op.f("ix_daily_checkin_user_id"), table_name="daily_checkin")
    op.drop_index(op.f("ix_daily_checkin_id"), table_name="daily_checkin")
    op.drop_table("daily_checkin")
