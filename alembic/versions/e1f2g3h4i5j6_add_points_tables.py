"""add_points_tables

Revision ID: e1f2g3h4i5j6
Revises: c1d2e3f4g5h6
Create Date: 2026-03-04 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2g3h4i5j6"
down_revision: Union[str, None] = "c1d2e3f4g5h6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 创建 user_points 表
    if not insp.has_table("user_points"):
        op.create_table(
            "user_points",
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("points", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
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
            sa.PrimaryKeyConstraint("user_id", "chat_id"),
        )
        op.create_index(
            op.f("ix_user_points_user_id"), "user_points", ["user_id"], unique=False
        )
        op.create_index(
            op.f("ix_user_points_chat_id"), "user_points", ["chat_id"], unique=False
        )

    # 创建 points_transaction 表
    if not insp.has_table("points_transaction"):
        op.create_table(
            "points_transaction",
            sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("amount", sa.BigInteger(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("operator_id", sa.BigInteger(), nullable=True),
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
        )
        op.create_index(
            op.f("ix_points_transaction_id"),
            "points_transaction",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_points_transaction_user_id"),
            "points_transaction",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_points_transaction_chat_id"),
            "points_transaction",
            ["chat_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_points_transaction_operator_id"),
            "points_transaction",
            ["operator_id"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_points_transaction_operator_id"),
        table_name="points_transaction",
    )
    op.drop_index(
        op.f("ix_points_transaction_chat_id"),
        table_name="points_transaction",
    )
    op.drop_index(
        op.f("ix_points_transaction_user_id"),
        table_name="points_transaction",
    )
    op.drop_index(
        op.f("ix_points_transaction_id"),
        table_name="points_transaction",
    )
    op.drop_table("points_transaction")

    op.drop_index(op.f("ix_user_points_chat_id"), table_name="user_points")
    op.drop_index(op.f("ix_user_points_user_id"), table_name="user_points")
    op.drop_table("user_points")
